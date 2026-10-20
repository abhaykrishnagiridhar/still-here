"""The operator server: serves the pages, the live video with the plan drawn on it, and the
buttons (tap the survivor, approve, abort, report, drive by hand).

Run it from the laptop folder:
    python server.py                       the real rover: still-here.local, and its own video stream
    python server.py --rover 192.168.0.50  the real rover at an address (add :port if it is not 81)
    python server.py 1                     use webcam 1 for the picture instead of the rover's stream
    python server.py clip.avi --simulate   the software rover and a recorded clip, no hardware
Then open http://127.0.0.1:8000/ (autonomous) or http://127.0.0.1:8000/control.html (manual).
For a phone or another laptop on the same Wi-Fi add --host 0.0.0.0: the server prints an access link
with a token; open it once on that device. This laptop never needs the token, other devices do.

The rover's name, port and stream path come from config.toml ([rover]); the rover firmware is
expected to announce the name still-here on the network. If the rover cannot be reached, the pages
say so and nothing is sent. To try the whole real-rover path with no hardware, run
`python sim_server.py` in another window and start this with `--rover 127.0.0.1`.

Only pages from this machine or the local network may press a button (origin_guard.py). The
server listens on this machine only unless you pass --host.
"""

import argparse
import logging
import secrets
import socket
import sys
import threading
import time
from dataclasses import replace
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Callable, Iterator, Optional, Sequence

import cv2
import numpy as np
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel

from aruco import Config
from blender_link import BlenderLink
from demo_world import HEAT_RADIUS_MM
from autopilot import Autopilot
from calibrate import DEFAULT_FILE as CALIBRATION_FILE
from calibrate import Calibration
from calibrate import load as load_calibration
from experience import Experience
from manual_core import Manual
from operator_core import Link, Operator
from origin_guard import host_allowed, origin_allowed
from report import build_report, choose_summary, write_report
from rover_link import RealLink
from sim_rover import SimRover
from stream import FrameSource
from vision import MAX_FAILED_READS, MAX_RECONNECTS, Pipeline, clock_for, open_source

log = logging.getLogger("still_here.server")

LAPTOP_DIR = Path(__file__).resolve().parent
WEB_DIR = LAPTOP_DIR / "web"  # the pages and their scripts and styles
# Only these files in web/ are ever served, so config.toml and the source code never are.
PAGES = {
    "index.html", "autonomous.html", "control.html", "blueprint.html", "terms.html", "privacy.html",
    "landing.css", "landing.js", "operator.css", "operator.js", "control.js", "api.js", "ui_logic.js",
}
FRAME_SIZE = (640, 480)
STEP_S = 0.05  # how often the simulated rover is advanced
PING_S = 0.5
JPEG_QUALITY = 80
EXPERIENCE_FILE = LAPTOP_DIR / "experience.json"  # git-ignored; what past runs taught the planner
REPORT_FILE = LAPTOP_DIR / "safe_path_report.json"  # git-ignored; rewritten when a run ends
TOKEN_COOKIE = "still_here_token"
TOKEN_HEADER = "x-still-here-token"
TOKEN_LIFETIME_S = 12 * 3600
LOOPBACK_HOSTS = ("127.0.0.1", "::1", "localhost")
FILE_FRAME_S = 1 / 30  # a video file is played at about 30 pictures a second


def mjpeg_chunks(
    get_jpeg: Callable[[], bytes], should_stop: Callable[[], bool], wait: Callable[[], None]
) -> Iterator[bytes]:
    """The parts of a motion-JPEG stream: one picture after another."""
    while not should_stop():
        jpeg = get_jpeg()
        header = f"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: {len(jpeg)}\r\n\r\n"
        yield header.encode() + jpeg + b"\r\n"
        wait()


def _encode(image: np.ndarray) -> bytes:
    ok, buffer = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
    if not ok:
        raise RuntimeError("could not encode the picture as JPEG")
    return buffer.tobytes()


def _waiting_picture() -> bytes:
    image = np.zeros((FRAME_SIZE[1], FRAME_SIZE[0], 3), dtype=np.uint8)
    cv2.putText(image, "Waiting for the camera...", (150, 245), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (200, 200, 200), 2)
    return _encode(image)


class Capture:
    """Runs the camera pipeline on each picture and keeps the newest annotated one."""

    def __init__(self, pipeline: Pipeline, operator: Operator, lock: threading.RLock) -> None:
        self._pipeline = pipeline
        self._operator = operator
        self._lock = lock
        self._jpeg = _waiting_picture()
        self.frame_size = FRAME_SIZE
        self.error: Optional[str] = None

    def process(self, frame: np.ndarray, now: float) -> None:
        with self._lock:
            hint = self._operator.survivor_hint
        result = self._pipeline.process(frame, now, survivor_hint=hint)
        jpeg = _encode(result.shown)
        with self._lock:
            self._operator.observe(result)
            self._jpeg = jpeg
            self.frame_size = (frame.shape[1], frame.shape[0])
            self.error = None

    def latest_jpeg(self) -> bytes:
        with self._lock:
            return self._jpeg


class SimLink:
    """A rover that exists only in software. When a plan arrives it is set up with the blocks the
    camera currently sees, so picking them up has something to find."""

    connected = True  # a software rover is always there
    address = "the simulated rover"
    last_error = ""

    def __init__(self, get_blocks: Callable[[], Sequence]) -> None:
        self._get_blocks = get_blocks
        self._rover = SimRover()
        self._inbox: list[dict] = []
        self._since_ping = PING_S  # ping straight away

    def send(self, message: dict) -> None:
        if message.get("type") == "plan":
            self._rover = SimRover(self._get_blocks())
            self._since_ping = PING_S
        self._inbox += self._rover.handle(message)

    def advance(self, dt: float) -> list[dict]:
        self._since_ping += dt
        if self._since_ping >= PING_S:
            self._since_ping = 0.0
            self._inbox += self._rover.handle({"type": "ping", "t": self._rover.t})
        out, self._inbox = self._inbox + self._rover.step(dt), []
        return out


class Tap(BaseModel):
    x: float
    y: float


class Approval(BaseModel):
    key: str


class Drive(BaseModel):
    left: float
    right: float


class ArmPose(BaseModel):
    base: float
    shoulder: float
    elbow: float
    gripper: float
    speed: float = 1.0


def create_app(
    source: Optional[str] = None,
    config: Optional[Config] = None,
    report_writer: Callable = write_report,
    report_path: Path = REPORT_FILE,
    calibration: Optional[Calibration] = None,
    manual_clock: Callable[[], float] = time.monotonic,
    link: Optional[Link] = None,
    access_token: Optional[str] = None,
    experience: Optional[Experience] = None,
    autopilot_episodes: Optional[int] = None,
) -> FastAPI:
    """Build the server. With a source it also reads that camera once it is started; with
    none (as in tests) nothing runs in the background."""
    lock = threading.RLock()
    stop = threading.Event()
    holder: dict[str, Operator] = {}

    def blocks_seen() -> Sequence:
        with lock:
            return holder["operator"].latest_blocks()

    link = link if link is not None else SimLink(blocks_seen)
    operator = Operator(link)
    holder["operator"] = operator
    experience = experience if experience is not None else Experience()  # in memory unless given a file
    pipeline = Pipeline(config, calibration)
    pipeline.extra_clearance_mm = experience.extra_clearance_mm
    capture = Capture(pipeline, operator, lock)
    manual = Manual(link, is_busy=operator.busy, clock=manual_clock)
    autopilot: Optional[Autopilot] = None
    if autopilot_episodes is not None:
        if not getattr(link, "supports_world_reset", False):
            raise ValueError("Autonomous mode only runs against the simulated Blender rover, never a real one.")
        autopilot = Autopilot(
            operator, link, episodes=autopilot_episodes,
            extra_clearance=lambda: experience.extra_clearance_mm,
            corridor_mm=(config if config is not None else Config()).corridor_mm,
        )

    def advance(dt: float) -> None:
        with lock:
            operator.on_rover(link.advance(dt))
            operator.tick()
            manual.tick()  # stops the wheels if the control page stopped sending
            finished = operator.take_finished_facts()
        if finished is not None:  # a run just ended: learn from it, save the report file and chime once
            with lock:
                experience.record(finished, disturbed=bool(finished.get("disturbed_neighbour")))
                pipeline.extra_clearance_mm = experience.extra_clearance_mm
            report_writer(finished, str(report_path), choose_summary(build_report(finished)))
        if autopilot is not None:
            with lock:
                autopilot.tick()

    def require_rover() -> None:
        if not getattr(link, "connected", True):
            raise HTTPException(
                status_code=409,
                detail=f"The rover is not connected ({getattr(link, 'address', '')}). Nothing was sent. "
                "It stops by itself when it hears nothing for 2 seconds.",
            )

    def has_access(request: Request) -> bool:
        """Open to anyone when no token is set. With one, only this laptop, or a device that
        brought the token (in the cookie the access link sets, or in a header), gets in."""
        if access_token is None:
            return True
        if request.client is not None and request.client.host in LOOPBACK_HOSTS:
            return True
        supplied = request.cookies.get(TOKEN_COOKIE) or request.headers.get(TOKEN_HEADER) or ""
        return secrets.compare_digest(supplied.encode(), access_token.encode())

    def require_token(request: Request) -> None:
        if not has_access(request):
            raise HTTPException(
                status_code=401,
                detail="This page needs the access link the server printed when it started. Open that link once.",
            )

    def guard(request: Request) -> None:
        if not origin_allowed(request.headers.get("origin")):
            raise HTTPException(status_code=403, detail="This page may not control the rover.")
        require_token(request)

    def sign_in(request: Request, target: str) -> RedirectResponse:
        """Go to the page at its clean address, remembering the token if the link carried the right one."""
        response = RedirectResponse(target)
        offered = request.query_params.get("token")
        if access_token is not None and offered and secrets.compare_digest(offered.encode(), access_token.encode()):
            response.set_cookie(TOKEN_COOKIE, access_token, httponly=True, samesite="strict", max_age=TOKEN_LIFETIME_S)
        return response

    def run_rover() -> None:
        while not stop.is_set():
            try:
                advance(STEP_S)
            except Exception:  # one bad message must not stop the loop that keeps the rover's link alive
                log.exception("rover loop step failed; carrying on")
            time.sleep(STEP_S)

    def read_camera() -> None:
        is_file = Path(source).is_file()
        frames = FrameSource(
            lambda: open_source(source),
            max_failed_reads=MAX_FAILED_READS,
            max_reconnects=0 if is_file else MAX_RECONNECTS,
            sleep=time.sleep,
        )
        clock = clock_for(source)
        try:
            while not stop.is_set():
                frame = frames.read()
                if frames.gave_up:
                    if not is_file:  # a finished video file just leaves its last picture up
                        with lock:
                            capture.error = "Lost the camera and could not reconnect."
                    break
                if frame is not None:
                    try:
                        capture.process(frame, clock())
                    except Exception as error:  # say so on the page, keep reading pictures
                        log.exception("could not process a picture")
                        with lock:
                            capture.error = f"Could not process the picture: {type(error).__name__}."
                    if is_file:
                        time.sleep(FILE_FRAME_S)  # play a clip at about its normal speed
        finally:
            frames.close()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if source is not None:
            for target in (run_rover, read_camera):
                threading.Thread(target=target, daemon=True).start()
        starter = getattr(link, "start", None)
        if starter is not None:
            starter()  # a real rover link connects in the background and keeps itself connected
        yield
        stop.set()
        closer = getattr(link, "close", None)
        if closer is not None:
            closer()

    app = FastAPI(title="STILL HERE operator", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.source = source
    app.state.operator = operator
    app.state.capture = capture
    app.state.pipeline = pipeline
    app.state.experience = experience
    app.state.link = link
    app.state.advance = advance
    app.state.manual = manual
    app.state.autopilot = autopilot

    @app.middleware("http")
    async def only_local_hosts(request: Request, call_next):
        if not host_allowed(request.headers.get("host")):
            return JSONResponse({"detail": "Open this page by the laptop's address, not by a public name."}, status_code=400)
        return await call_next(request)

    @app.get("/")
    def root(request: Request) -> RedirectResponse:
        return sign_in(request, "/autonomous.html")

    @app.get("/video", dependencies=[Depends(require_token)])
    def video() -> StreamingResponse:
        chunks = mjpeg_chunks(capture.latest_jpeg, stop.is_set, lambda: time.sleep(STEP_S))
        return StreamingResponse(chunks, media_type="multipart/x-mixed-replace; boundary=frame")

    @app.get("/api/state", dependencies=[Depends(guard)])
    def state() -> dict:
        with lock:
            body = operator.state()
            body["frame"] = {"w": capture.frame_size[0], "h": capture.frame_size[1]}
            body["camera_error"] = capture.error
            body["learned"] = experience.explanation
            body["rover_connected"] = bool(getattr(link, "connected", True))
            body["rover_address"] = str(getattr(link, "address", ""))
            body["rover_error"] = str(getattr(link, "last_error", ""))
            body["autopilot"] = autopilot.summary() if autopilot is not None else None
            return body

    @app.get("/api/report", dependencies=[Depends(guard)])
    def report() -> dict:
        with lock:
            return {"report": operator.report(), "text": operator.report_text()}

    @app.post("/api/survivor", dependencies=[Depends(guard)])
    def survivor(tap: Tap) -> dict:
        width, height = capture.frame_size
        if not (0 <= tap.x < width and 0 <= tap.y < height):
            raise HTTPException(status_code=422, detail="That spot is outside the picture.")
        with lock:
            operator.tap_survivor(tap.x, tap.y)
        return {"ok": True}

    @app.post("/api/survivor/clear", dependencies=[Depends(guard)])
    def clear_survivor() -> dict:
        with lock:
            operator.clear_survivor()
        return {"ok": True}

    @app.post("/api/approve", dependencies=[Depends(guard)])
    def approve(approval: Approval) -> dict:
        require_rover()
        with lock:
            outcome = operator.approve(approval.key)
        if not outcome.ok:
            raise HTTPException(status_code=409, detail=outcome.message)
        return {"ok": True, "message": outcome.message}

    @app.post("/api/abort", dependencies=[Depends(guard)])
    def abort() -> dict:
        with lock:
            operator.abort()
        return {"ok": True}

    @app.post("/api/reset", dependencies=[Depends(guard)])
    def reset() -> dict:
        with lock:
            operator.reset()
        return {"ok": True}

    def refused_or_ok(outcome) -> dict:
        if not outcome.ok:
            raise HTTPException(status_code=409, detail=outcome.message)
        return {"ok": True, "message": outcome.message}

    @app.post("/api/manual/drive", dependencies=[Depends(guard)])
    def manual_drive(body: Drive) -> dict:
        require_rover()
        with lock:
            return refused_or_ok(manual.drive(body.left, body.right))

    @app.post("/api/manual/arm", dependencies=[Depends(guard)])
    def manual_arm(body: ArmPose) -> dict:
        require_rover()
        with lock:
            return refused_or_ok(manual.arm_pose(body.base, body.shoulder, body.elbow, body.gripper, body.speed))

    @app.post("/api/manual/stop", dependencies=[Depends(guard)])
    def manual_stop() -> dict:
        require_rover()
        with lock:
            return refused_or_ok(manual.stop())

    @app.get("/{name}")  # last, so it never shadows the routes above
    def page(name: str, request: Request):
        if name not in PAGES:
            raise HTTPException(status_code=404)
        if request.query_params.get("token"):
            return sign_in(request, f"/{name}")  # an access link: remember the token, show the clean address
        return FileResponse(WEB_DIR / name)

    return app


def access_token_for(host: str, explicit: Optional[str]) -> Optional[str]:
    """A server open to the network gets an access token (a new one each start unless you give one).
    One that listens on this laptop only needs none, because nothing else can reach it."""
    if explicit:
        return explicit
    if host in LOOPBACK_HOSTS:
        return None
    return secrets.token_urlsafe(9)


def lan_address(make_socket: Optional[Callable] = None) -> str:
    """This laptop's address on the Wi-Fi, found without sending anything, or 127.0.0.1."""
    probe = (make_socket or (lambda: socket.socket(socket.AF_INET, socket.SOCK_DGRAM)))()
    try:
        probe.connect(("10.255.255.255", 1))  # a UDP connect sends nothing: it only picks the network card
        return probe.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        probe.close()


def config_for_blender(config: Config) -> Config:
    """The Blender demo's table-top fire pad is 56 mm wide, so the project's default 100 mm keep-out would fill
    the picture. Use the demo's smaller radius, unless the person's own config already chose one."""
    if config.heat_radius_mm == Config().heat_radius_mm:
        return replace(config, heat_radius_mm=HEAT_RADIUS_MM)
    return config


def choose_rover(
    simulate: bool,
    rover_arg: Optional[str],
    source_arg: Optional[str],
    config: Config,
    blender_port: Optional[int] = None,
) -> tuple[Optional[Link], str]:
    """The rover link and the camera source to use. The rover is `still-here.local` (or whatever
    config.toml says) unless --rover names another; --simulate uses the software rover and a webcam."""
    if blender_port is not None:
        if simulate or rover_arg:
            raise ValueError("--blender cannot be combined with --simulate or --rover")
        if not 0 < blender_port < 65536:
            raise ValueError(f"--blender needs the twin's UDP port, from 1 to 65535, got {blender_port}")
        return BlenderLink(blender_port), source_arg or f"blender:{blender_port}"
    if simulate:
        return None, source_arg or "0"
    host, port = config.rover_host, config.ws_port
    if rover_arg:
        host, _, port_text = rover_arg.partition(":")
        if not host:
            raise ValueError("--rover needs a name or address, such as still-here.local or 192.168.0.50:81")
        if port_text:
            if not port_text.isdigit() or not 0 < int(port_text) < 65536:
                raise ValueError(f"--rover port must be a number from 1 to 65535, got {port_text!r}")
            port = int(port_text)
    return RealLink(host, port), source_arg or f"http://{host}{config.stream_path}"


def main(argv: Optional[Sequence[str]] = None) -> int:
    from aruco import load_config

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="STILL HERE operator server")
    parser.add_argument("source", nargs="?", help="webcam number, stream URL or video file (default: the rover's own stream)")
    parser.add_argument("--rover", help="the rover's name or address, optionally with a port (default: config.toml, normally still-here.local)")
    parser.add_argument("--blender", type=int, metavar="PORT", help="use the Blender twin (simulation/blender_rover.py) as the rover and the camera; PORT is its UDP port, normally 8766")
    parser.add_argument("--auto", action="store_true", help="autonomous demo: the laptop approves its own plans and learns from each run. Only with --blender")
    parser.add_argument("--episodes", type=int, default=3, help="how many runs --auto makes on the same course (default 3)")
    parser.add_argument("--remember", action="store_true", help="with --auto: start from what past runs taught (experience.json) instead of untrained")
    parser.add_argument("--simulate", action="store_true", help="use the software rover and a webcam, with no real rover")
    parser.add_argument("--host", default="127.0.0.1", help="use 0.0.0.0 to open the pages to phones and other laptops on the same Wi-Fi")
    parser.add_argument("--token", help="the access token for devices other than this laptop (default: a new one each start)")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    try:
        config = load_config()
        calibration = load_calibration() if CALIBRATION_FILE.exists() else None
    except ValueError as error:
        print(f"Config or calibration problem: {error}", file=sys.stderr)
        return 1
    if calibration is None:
        print("No calibration.json: using a flat scale from the block size. "
              "For a camera at an angle, run calibrate.py.")
    try:
        link, source = choose_rover(args.simulate, args.rover, args.source, config, blender_port=args.blender)
        if args.blender is not None:
            config = config_for_blender(config)
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1
    if args.auto and args.blender is None:
        print("--auto only runs against the Blender twin (--blender PORT). It will not drive a real rover.", file=sys.stderr)
        return 1
    if args.auto and args.episodes < 1:
        print("--episodes must be at least 1", file=sys.stderr)
        return 1
    print(f"Rover: {link.address}" if link is not None else "Rover: the simulated rover (--simulate)")
    print(f"Camera: {source}")
    if args.auto:
        print(f"Autonomous demo: {args.episodes} runs on the same course; the laptop approves its own plans and learns. "
              "Press Stop on the page to take over.")
    token = access_token_for(args.host, args.token)
    print(f"On this laptop:  http://127.0.0.1:{args.port}/")
    if token is not None:
        address = lan_address() if args.host in ("0.0.0.0", "::") else args.host
        print("On a phone or another laptop on the same Wi-Fi, open this access link once:")
        print(f"  http://{address}:{args.port}/?token={token}")
        print("Anyone with that link can drive the rover, so share it only with your team. It changes each time the server starts,")
        print("and it is plain http, so use a network you trust, such as your own phone hotspot.")
    import uvicorn

    uvicorn.run(
        create_app(
            source, config, calibration=calibration, link=link, access_token=token,
            experience=Experience(EXPERIENCE_FILE if (args.remember or not args.auto) else None),
            autopilot_episodes=args.episodes if args.auto else None,
        ), host=args.host, port=args.port
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
