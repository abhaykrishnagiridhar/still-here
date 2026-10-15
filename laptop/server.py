"""The operator server: serves the pages, the live video with the plan drawn on it, and the
buttons (tap the survivor, approve, abort, report, drive by hand).

Run it from the laptop folder:
    python server.py                       the real rover: still-here.local, and its own video stream
    python server.py --rover 192.168.0.50  the real rover at an address (add :port if it is not 81)
    python server.py 1                     use webcam 1 for the picture instead of the rover's stream
    python server.py clip.avi --simulate   the software rover and a recorded clip, no hardware
Then open http://127.0.0.1:8000/ (autonomous) or http://127.0.0.1:8000/control.html (manual).

The rover's name, port and stream path come from config.toml ([rover]); the rover firmware is
expected to announce the name still-here on the network. If the rover cannot be reached, the pages
say so and nothing is sent. To try the whole real-rover path with no hardware, run
`python sim_server.py` in another window and start this with `--rover 127.0.0.1`.

Only pages from this machine or the local network may press a button (origin_guard.py). The
server listens on this machine only unless you pass --host.
"""

import argparse
import sys
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Callable, Iterator, Optional, Sequence

import cv2
import numpy as np
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel

from aruco import Config
from calibrate import DEFAULT_FILE as CALIBRATION_FILE
from calibrate import Calibration
from calibrate import load as load_calibration
from manual_core import Manual
from operator_core import Link, Operator
from origin_guard import origin_allowed
from report import build_report, choose_summary, write_report
from rover_link import RealLink
from sim_rover import SimRover
from stream import FrameSource
from vision import MAX_FAILED_READS, MAX_RECONNECTS, Pipeline, clock_for, open_source

LAPTOP_DIR = Path(__file__).resolve().parent
# Only these files are ever served, so config.toml and the source code never are.
PAGES = {
    "index.html", "autonomous.html", "control.html", "blueprint.html", "terms.html", "privacy.html",
    "landing.css", "landing.js", "operator.css", "operator.js", "control.js", "api.js", "ui_logic.js",
}
FRAME_SIZE = (640, 480)
STEP_S = 0.05  # how often the simulated rover is advanced
PING_S = 0.5
JPEG_QUALITY = 80
REPORT_FILE = LAPTOP_DIR / "safe_path_report.json"  # git-ignored; rewritten when a run ends
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
    capture = Capture(Pipeline(config, calibration), operator, lock)
    manual = Manual(link, is_busy=operator.busy, clock=manual_clock)

    def advance(dt: float) -> None:
        with lock:
            operator.on_rover(link.advance(dt))
            operator.tick()
            manual.tick()  # stops the wheels if the control page stopped sending
            finished = operator.take_finished_facts()
        if finished is not None:  # a run just ended: save the report file and chime once
            report_writer(finished, str(report_path), choose_summary(build_report(finished)))

    def require_rover() -> None:
        if not getattr(link, "connected", True):
            raise HTTPException(
                status_code=409,
                detail=f"The rover is not connected ({getattr(link, 'address', '')}). Nothing was sent. "
                "It stops by itself when it hears nothing for 2 seconds.",
            )

    def guard(request: Request) -> None:
        if not origin_allowed(request.headers.get("origin")):
            raise HTTPException(status_code=403, detail="This page may not control the rover.")

    def run_rover() -> None:
        while not stop.is_set():
            advance(STEP_S)
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
                    capture.process(frame, clock())
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

    app = FastAPI(title="STILL HERE operator", lifespan=lifespan)
    app.state.source = source
    app.state.operator = operator
    app.state.capture = capture
    app.state.link = link
    app.state.advance = advance
    app.state.manual = manual

    @app.get("/")
    def root() -> RedirectResponse:
        return RedirectResponse("/autonomous.html")

    @app.get("/video")
    def video() -> StreamingResponse:
        chunks = mjpeg_chunks(capture.latest_jpeg, stop.is_set, lambda: time.sleep(STEP_S))
        return StreamingResponse(chunks, media_type="multipart/x-mixed-replace; boundary=frame")

    @app.get("/api/state", dependencies=[Depends(guard)])
    def state() -> dict:
        with lock:
            body = operator.state()
            body["frame"] = {"w": capture.frame_size[0], "h": capture.frame_size[1]}
            body["camera_error"] = capture.error
            body["rover_connected"] = bool(getattr(link, "connected", True))
            body["rover_address"] = str(getattr(link, "address", ""))
            body["rover_error"] = str(getattr(link, "last_error", ""))
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
    def page(name: str) -> FileResponse:
        if name not in PAGES:
            raise HTTPException(status_code=404)
        return FileResponse(LAPTOP_DIR / name)

    return app


def choose_rover(
    simulate: bool, rover_arg: Optional[str], source_arg: Optional[str], config: Config
) -> tuple[Optional[RealLink], str]:
    """The rover link and the camera source to use. The rover is `still-here.local` (or whatever
    config.toml says) unless --rover names another; --simulate uses the software rover and a webcam."""
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

    parser = argparse.ArgumentParser(description="STILL HERE operator server")
    parser.add_argument("source", nargs="?", help="webcam number, stream URL or video file (default: the rover's own stream)")
    parser.add_argument("--rover", help="the rover's name or address, optionally with a port (default: config.toml, normally still-here.local)")
    parser.add_argument("--simulate", action="store_true", help="use the software rover and a webcam, with no real rover")
    parser.add_argument("--host", default="127.0.0.1", help="use 0.0.0.0 to open it to the local network")
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
        link, source = choose_rover(args.simulate, args.rover, args.source, config)
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1
    print(f"Rover: {link.address}" if link is not None else "Rover: the simulated rover (--simulate)")
    print(f"Camera: {source}")
    import uvicorn

    uvicorn.run(create_app(source, config, calibration=calibration, link=link), host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
