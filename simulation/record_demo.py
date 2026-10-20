"""Record a video of the autonomous loop running against the Blender twin.

Start these first (see docs/autonomy-demo.md):
    blender --python simulation/blender_rover.py          (or the headless runner)
    python laptop/server.py --blender 8766                the real server, using Blender as camera and rover

then:
    python simulation/record_demo.py --out demo.mp4

For the autonomous, learning version, start the server with `--auto --episodes 3` instead. The laptop then approves
its own plans and runs the same course several times, and this script just records, listing what each run taught it.

It watches the live system and does what the human operator does: it waits for the plan, shows it for a few seconds,
and presses Approve (unless the server is in autonomous mode, where nobody needs to). Left of the picture is the Blender scene in 3D, right is what the laptop's vision sees with the
plan drawn on it, and underneath is a plain caption of the step the loop is in. Nothing is staged: every frame comes
from the running system, and the numbers in the captions are the server's own.
"""

import argparse
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

SIMULATION = Path(__file__).resolve().parent
LAPTOP = SIMULATION.parent / "laptop"
if str(LAPTOP) not in sys.path:
    sys.path.insert(0, str(LAPTOP))

from snapshot_client import request_picture

FRAMES_DIR = SIMULATION / "frames"
WIDTH, HEIGHT = 1280, 720
PANEL_W, PANEL_H = 640, 480
TOP = 44
BOTTOM = TOP + PANEL_H  # the caption area starts here

BACKGROUND = (26, 22, 20)  # BGR
PANEL_BACKGROUND = (40, 34, 30)
WHITE = (240, 240, 240)
GREY = (190, 190, 190)
DIM = (130, 130, 130)
ORANGE = (0, 150, 255)
GREEN = (120, 205, 120)
RED = (90, 90, 235)
FONT = cv2.FONT_HERSHEY_SIMPLEX


# ---- words ---------------------------------------------------------------------------------


def caption_for(state: dict) -> tuple[str, str]:
    """A heading and one line of detail for what the loop is doing, from the server's state."""
    phase = state.get("phase", "")
    progress = state.get("progress") or {}
    done, total = progress.get("done", 0), progress.get("total", 0)
    message = state.get("message", "")
    notice = state.get("notice")
    if phase == "plan_ready" and notice:
        return "RE-PLAN  The scene changed, so the rover stopped and a fresh plan is ready", notice
    if phase == "scanning":
        return "1. SEE  Looking for blocks, fire and the survivor's pulsing light", message
    if phase == "need_survivor":
        return "1. SEE  The survivor's light is not found yet", message
    if phase == "plan_ready":
        if state.get("autopilot"):
            return (
                "2. PLAN  The planner proposes the safest way to the survivor",
                "Autonomous mode: the laptop checks the plan and approves it itself. Pressing Stop takes over.",
            )
        return (
            "2. PLAN  The planner proposes the safest way to the survivor",
            "A human must review and approve it before the rover moves.",
        )
    if phase == "waiting":
        return "3. RUN  Approved by the human. Sending the plan to the rover", message
    if phase == "running":
        return (
            "3. RUN  The rover removes the blocks one at a time",
            f"{done} of {total} steps done. The camera keeps watching for anything unexpected.",
        )
    if phase == "verifying":
        return "4. CHECK  The camera confirms the way to the survivor is clear", message
    if phase == "done":
        return "5. DONE  Verified clear by the camera, and the report is written", message
    if phase == "aborted":
        return "STOPPED  The run was stopped for safety", message
    return phase.replace("_", " ").upper() or "STILL HERE", message


def learning_lines(autopilot: Optional[dict]) -> list[str]:
    """One line per finished run of autonomous mode: what it did, and what the laptop took from it."""
    if not autopilot:
        return []
    lines = []
    for run in autopilot.get("history", []):
        moved = run["moved"]
        start = f"Run {run['number']}: moved {moved} block{'' if moved == 1 else 's'}."
        if run["outcome"] == "bumped":
            what = run.get("brushed") or "a block"
            lines.append(f"{start} Brushed {what}, so the corridor grows to {run['next_corridor_mm']:.0f} mm.")
        elif run["outcome"] == "clean":
            lines.append(f"{start} Clean, with a {run['corridor_mm']:.0f} mm corridor.")
        else:
            lines.append(f"{start} The camera could not confirm the way was clear.")
    return lines


def plan_lines(plan: Optional[dict]) -> list[str]:
    """The plan as lines of text: what is removed, in order, and what stays and why."""
    if not plan:
        return []
    lines = [
        f"Remove {item['n']}: block_{item['id']} at ({item['x']:.0f}, {item['y']:.0f}) mm" for item in plan.get("order", [])
    ]
    lines += [f"Leave block_{item['id']}: {item['reason']}" for item in plan.get("left", [])]
    return lines


# ---- pictures in the video stream ---------------------------------------------------------


def extract_jpeg(buffer: bytes) -> tuple[Optional[bytes], bytes]:
    """The first whole JPEG in the buffer and what comes after it, or (None, the part worth keeping)."""
    start = buffer.find(b"\xff\xd8")
    if start < 0:
        return None, buffer[-1:]
    end = buffer.find(b"\xff\xd9", start + 2)
    if end < 0:
        return None, buffer[start:]
    return buffer[start : end + 2], buffer[end + 2 :]


# ---- drawing ------------------------------------------------------------------------------


def _text(image, text, origin, scale=0.55, colour=WHITE, thickness=1) -> None:
    cv2.putText(image, text, origin, FONT, scale, colour, thickness, cv2.LINE_AA)


def _fit(image: Optional[np.ndarray], width: int, height: int) -> np.ndarray:
    """The picture scaled to fit the box without bending it, centred on a dark panel."""
    panel = np.full((height, width, 3), PANEL_BACKGROUND, dtype=np.uint8)
    if image is None or image.size == 0:
        _text(panel, "waiting for a picture...", (20, height // 2), 0.6, DIM)
        return panel
    scale = min(width / image.shape[1], height / image.shape[0])
    resized = cv2.resize(image, (max(1, int(image.shape[1] * scale)), max(1, int(image.shape[0] * scale))))
    y0, x0 = (height - resized.shape[0]) // 2, (width - resized.shape[1]) // 2
    panel[y0 : y0 + resized.shape[0], x0 : x0 + resized.shape[1]] = resized
    return panel


def compose(blender_image, operator_image, state: dict, hint: str = "") -> np.ndarray:
    """One video frame: the 3D scene, the laptop's view, and the caption underneath."""
    frame = np.full((HEIGHT, WIDTH, 3), BACKGROUND, dtype=np.uint8)
    _text(frame, "STILL HERE   autonomous rescue loop, Blender simulation", (16, 29), 0.7, WHITE, 2)
    frame[TOP:BOTTOM, 0:PANEL_W] = _fit(blender_image, PANEL_W, PANEL_H)
    frame[TOP:BOTTOM, PANEL_W:WIDTH] = _fit(operator_image, PANEL_W, PANEL_H)
    _text(frame, "Blender: the simulated rover and table", (14, TOP + 22), 0.5, WHITE)
    _text(frame, "Laptop view: vision + plan", (PANEL_W + 14, TOP + 22), 0.5, WHITE)

    heading, detail = caption_for(state)
    colour = GREEN if heading.startswith(("5.", "4.")) else RED if heading.startswith("STOPPED") else ORANGE
    _text(frame, heading, (16, BOTTOM + 30), 0.78, colour, 2)
    _text(frame, detail[:120], (16, BOTTOM + 56), 0.55, GREY)

    progress = state.get("progress") or {}
    total = progress.get("total", 0)
    if total:
        cv2.rectangle(frame, (16, BOTTOM + 70), (16 + 400, BOTTOM + 84), (70, 64, 60), -1)
        filled = int(400 * min(1.0, progress.get("done", 0) / total))
        cv2.rectangle(frame, (16, BOTTOM + 70), (16 + filled, BOTTOM + 84), GREEN, -1)
        _text(frame, f"{progress.get('done', 0)} of {total} steps", (430, BOTTOM + 83), 0.5, GREY)

    lines = plan_lines(state.get("plan"))
    for index, line in enumerate(lines[:6]):
        _text(frame, line, (16, BOTTOM + 112 + 17 * index), 0.5, GREY if line.startswith("Remove") else DIM)
    auto = state.get("autopilot")
    if auto:
        _text(frame, f"LEARNING  run {auto['episode']} of {auto['episodes']}, corridor {auto['corridor_mm']:.0f} mm",
              (PANEL_W + 14, BOTTOM + 112), 0.55, ORANGE, 1)
        for index, line in enumerate(learning_lines(auto)[:4]):
            _text(frame, line[:80], (PANEL_W + 14, BOTTOM + 134 + 17 * index), 0.46, GREEN if "Clean" in line else GREY)
    if hint:
        _text(frame, hint, (WIDTH - 16 - 11 * len(hint), BOTTOM + 30), 0.55, WHITE)
    return frame


def title_card(title: str, lines: list[str], right_lines: Optional[list[str]] = None) -> np.ndarray:
    """A plain card with a title and lines of text, in one column or two."""
    card = np.full((HEIGHT, WIDTH, 3), BACKGROUND, dtype=np.uint8)
    cv2.rectangle(card, (60, 150), (68, 150 + 70), ORANGE, -1)
    _text(card, title, (92, 200), 1.15, WHITE, 2)
    scale, step = (0.62, 34) if right_lines is not None else (0.72, 42)
    for index, line in enumerate(lines):
        _text(card, line, (92, 290 + step * index), scale, GREY)
    for index, line in enumerate(right_lines or []):
        _text(card, line, (WIDTH // 2 + 20, 290 + step * index), scale, GREY)
    return card


def split_report(report_lines: list[str]) -> tuple[list[str], list[str]]:
    """The report's facts (up to its summary) and, separately, what happened to each block."""
    lines = [line.strip() for line in report_lines if line.strip() and "SAFE-PATH REPORT" not in line]
    for index, line in enumerate(lines):
        if line.startswith("Summary:"):
            return lines[: index + 1], lines[index + 1 :]
    return lines, []


# ---- talking to the live system ------------------------------------------------------------


class Approver:
    """Does what the human operator does: look at each plan for a few seconds, then approve it. A fresh plan offered
    after a safety stop is looked at and approved the same way, once per plan."""

    def __init__(self, approve_after_s: float) -> None:
        self._after = approve_after_s
        self._shown_at: Optional[float] = None
        self._approved = False

    def update(self, state: dict, now: float) -> bool:
        """True when the plan on show should be approved now."""
        phase = state.get("phase")
        if phase != "plan_ready":
            if phase not in ("scanning", "need_survivor"):  # those can flicker; the countdown carries on
                self._shown_at, self._approved = None, False
            return False
        if self._approved:
            return False
        if self._shown_at is None:
            self._shown_at = now
        if now - self._shown_at >= self._after:
            self._approved = True
            return True
        return False

    def remaining(self, now: float) -> float:
        return max(0.0, self._after - (now - self._shown_at)) if self._shown_at is not None else self._after


class Latest:
    """The newest picture from each source, written by background threads and read by the recorder."""

    def __init__(self) -> None:
        self.operator: Optional[np.ndarray] = None
        self.overview: Optional[np.ndarray] = None


def _read_operator_video(base: str, latest: Latest, stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            with urllib.request.urlopen(base + "/video", timeout=10) as stream:
                buffer = b""
                while not stop.is_set():
                    chunk = stream.read(8192)
                    if not chunk:
                        break
                    buffer += chunk
                    while True:
                        picture, buffer = extract_jpeg(buffer)
                        if picture is None:
                            break
                        image = cv2.imdecode(np.frombuffer(picture, dtype=np.uint8), cv2.IMREAD_COLOR)
                        if image is not None:
                            latest.operator = image
        except (OSError, urllib.error.URLError):
            time.sleep(1.0)


def _request_overview(port: int, latest: Latest, stop: threading.Event) -> None:
    path = FRAMES_DIR / f"overview_rec_{os.getpid()}.png"
    while not stop.is_set():
        result = request_picture(path, "overview", "127.0.0.1", port, 3.0)
        if result is not None:
            latest.overview = result[0]
        time.sleep(0.6)  # the 3D view needs far fewer pictures than the camera, and each one keeps Blender busy


def _get(base: str, path: str) -> dict:
    with urllib.request.urlopen(base + path, timeout=10) as response:
        return json.load(response)


def _post(base: str, path: str, body: dict) -> dict:
    origin = base.rstrip("/")
    request = urllib.request.Request(
        base + path, data=json.dumps(body).encode(), method="POST",
        headers={"Origin": origin, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)


def record(args) -> int:
    base = args.server.rstrip("/")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        state = _get(base, "/api/state")
    except (OSError, urllib.error.URLError) as problem:
        print(f"Cannot reach the server at {base}: {problem}", file=sys.stderr)
        return 2
    if not state.get("rover_connected"):
        print("The server is running but not connected to the Blender twin. Start Blender first.", file=sys.stderr)
        return 2

    writer = cv2.VideoWriter(str(out), cv2.VideoWriter_fourcc(*"mp4v"), args.fps, (WIDTH, HEIGHT))
    latest, stop = Latest(), threading.Event()
    threading.Thread(target=_read_operator_video, args=(base, latest, stop), daemon=True).start()
    threading.Thread(target=_request_overview, args=(args.blender_port, latest, stop), daemon=True).start()

    intro = title_card("An autonomous rescue loop, in simulation", [
        "See: the camera finds blocks, a fire pad and the survivor's pulsing light.",
        "Plan: the planner picks which blocks to remove and which to leave, and why.",
        "Approve: a human checks the plan. The rover never moves without it.",
        "Run, then check: the rover clears the path and the camera confirms it.",
    ])
    for _ in range(int(args.fps * 4)):
        writer.write(intro)

    started = time.time()
    done_at = None
    approver = Approver(args.approve_after)
    next_frame = time.time()
    frames = 0
    while time.time() - started < args.timeout:
        try:
            state = _get(base, "/api/state")
        except (OSError, urllib.error.URLError):
            pass  # keep the last state; the next poll will probably work
        now = time.time()
        hint = ""
        auto = state.get("autopilot")
        if auto:  # the laptop approves its own plans: nobody needs to, and the recording ends when its last run does
            if state.get("phase") == "plan_ready":
                hint = "laptop approves by itself"
            if not auto["active"]:  # it finished, or a person stopped it
                done_at = done_at or now
        elif approver.update(state, now):
            try:
                _post(base, "/api/approve", {"key": state["plan"]["key"]})
            except (OSError, urllib.error.URLError, KeyError, TypeError):
                pass  # the plan changed under us: the next frame shows the new one
        elif state.get("phase") == "plan_ready":
            hint = f"human approves in {approver.remaining(now):.0f} s"
        if not auto and state.get("phase") in ("done", "aborted"):
            done_at = done_at or now
        writer.write(compose(latest.overview, latest.operator, state, hint))
        frames += 1
        if done_at is not None and now - done_at >= args.after_done:
            break
        next_frame += 1.0 / args.fps
        time.sleep(max(0.0, next_frame - time.time()))
    stop.set()

    try:
        report = _get(base, "/api/report").get("text", "").splitlines()
    except (OSError, urllib.error.URLError):
        report = []
    facts, outcomes = split_report(report)
    outro = title_card("What the system wrote down", facts or ["(no report was available)"], outcomes)
    for _ in range(int(args.fps * 7)):
        writer.write(outro)
    lessons = learning_lines(state.get("autopilot"))
    if lessons:
        learned = title_card("What it learned between runs", [*lessons, "", state.get("learned") or ""])
        for _ in range(int(args.fps * 8)):
            writer.write(learned)
    honest = title_card("What this shows, and what it does not", [
        "Ran for real: the vision, the planner, the human approval step, the rover protocol",
        "and the camera check. They are the same code the physical rover will use.",
        "Simulated: the rover, its arm and the camera pictures come from the Blender twin.",
        "Not yet proven: the physical arm, and the 8 of 10 two-block benchmark.",
    ])
    for _ in range(int(args.fps * 6)):
        writer.write(honest)
    writer.release()
    print(f"Wrote {out} ({frames} live frames, {out.stat().st_size / 1e6:.1f} MB)")
    auto = state.get("autopilot")
    if auto:
        return 0 if len(auto["history"]) >= auto["episodes"] else 1
    return 0 if state.get("phase") == "done" else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Record a video of the autonomous loop in the Blender twin.")
    parser.add_argument("--server", default="http://127.0.0.1:8000")
    parser.add_argument("--blender-port", type=int, default=int(os.environ.get("STILL_HERE_UDP_PORT", "8766")))
    parser.add_argument("--out", default=str(SIMULATION / "frames" / "autonomy_demo.mp4"))
    parser.add_argument("--fps", type=float, default=10.0)
    parser.add_argument("--approve-after", type=float, default=6.0, help="seconds the plan is shown before the human approves")
    parser.add_argument("--after-done", type=float, default=4.0, help="seconds to keep recording after the run ends")
    parser.add_argument("--timeout", type=float, default=480.0, help="give up after this many seconds (autonomous mode needs several minutes)")
    return record(parser.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
