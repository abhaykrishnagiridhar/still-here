"""Rover vision and planning demo, ported from the C++ prototype and wired to planner.py.

Usage:
    python vision.py                                webcam 0
    python vision.py 1                              webcam 1
    python vision.py http://still-here.local/stream    the rover's camera stream
    python vision.py 0 --masks                      also show what the colour detectors see

Press ESC in the video window to quit.

What it does each frame:
- reads the ArUco marker on each block (aruco.py): id, top or bottom layer, heavy or light, and
  which bottom block a top block rests on. With no marker in view it falls back to red blocks
- tracks red blocks so each keeps an id, and sorts them with planner.plan()
- finds fire (steady bright orange or yellow) and leaves blocks near it alone
- finds the survivor light separately, as the one thing that PULSES, whatever its colour,
  and never counts a light at that spot as fire

Known limits (see docs/tasks.md for who owns the fix):
- Without markers, blocks are found by colour (red), which is fragile in a dim room, and
  every block is layer 1 with nothing resting on anything. Use markers for real runs.
- A bottom block whose marker is hidden by the block on top is not seen. Put the markers on
  the side faces the camera looks at.
- Coordinates are image pixels until the calibration tool maps them to millimetres.
- The survivor light needs about 1.5 seconds of video to be recognised, because it is
  found by its pulsing. Until then a bright orange light could briefly look like fire.
"""

import os
import sys
import time
from collections import deque
from dataclasses import dataclass
from math import hypot, sqrt
from typing import Optional, Sequence, Union

import cv2
import numpy as np

from aruco import Config, Marker, MarkerTracker, blocks_from_markers, find_markers, load_config
from calibrate import DEFAULT_FILE as CALIBRATION_FILE
from calibrate import Calibration
from calibrate import load as load_calibration
from models import Block, HeatZone
from planner import PlanResult
from route import RoutePlan
from scale import ScaleEstimator, block_size_ok, to_mm
from scene import Scene, build_scene, decide, path_in_px, scene_from_blocks, view_in_px
from stream import FrameSource

Point = tuple[int, int]

# Tunable values, all in one place.
MIN_BLOCK_AREA = 400.0  # pixels; smaller red blobs are noise
MAX_BLOCK_AREA = 30000.0  # pixels; bigger red regions, such as a table, are not blocks
MAX_BLOCK_ASPECT = 2.0  # a block's bounding box is never more than this much longer than wide
MIN_FIRE_AREA = 800.0  # pixels; smaller bright blobs are not a fire
MAX_FAILED_READS = 30  # blank frames in a row before the stream is reopened
MAX_RECONNECTS = 5  # times a dropped network camera is reopened before giving up
CONFIRM_FRAMES = 3  # frames in a row before a blob is believed
MAX_MISSING_FRAMES = 10  # frames a believed blob may vanish before it is forgotten
MAX_MATCH_DISTANCE_PX = 40  # how far a blob may move between frames and keep its id
WINDOW_NAME = "Rover Vision Window"

# The survivor light is found by pulsing, so these describe a pulse seen on a dark scene.
SURVIVOR_WINDOW_S = 1.5  # seconds of video to look at; at least two pulses at 1.5 Hz
SURVIVOR_MIN_FRAMES = 8  # frames needed before a verdict
SURVIVOR_MIN_SWING = 60  # brightness change (0 to 255) between the dim and bright phase
SURVIVOR_MIN_PEAK = 100  # the bright phase must reach at least this brightness
SURVIVOR_MIN_AREA = 60.0  # pixels, at full size
SURVIVOR_MIN_CROSSINGS = 3  # up and down changes in the window; one flash gives only two
SURVIVOR_SCALE = 0.25  # the survivor search runs on a quarter-size picture to stay fast
SURVIVOR_EXCLUDE_RADIUS_PX = 60.0  # lights this close to the survivor are never fire
WARMUP_SECONDS = SURVIVOR_WINDOW_S  # no plan is trusted until the survivor search has had this long

# Colour ranges in OpenCV HSV (hue 0 to 180). Tune them for your lighting.
RED_LOW = (np.array([0, 120, 70]), np.array([10, 255, 255]))
RED_HIGH = (np.array([170, 120, 70]), np.array([180, 255, 255]))  # red wraps around the hue circle
FIRE_RANGE = (np.array([15, 120, 230]), np.array([35, 255, 255]))  # bright orange to yellow only

GREEN = (0, 255, 0)
RED = (0, 0, 255)
ORANGE = (0, 140, 255)
CYAN = (255, 255, 0)

KNOWN_OPTIONS = {"--masks"}


def clean_mask(mask: np.ndarray) -> np.ndarray:
    """Remove speckles and fill small holes, so one block gives one blob."""
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    opened = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    return cv2.morphologyEx(opened, cv2.MORPH_CLOSE, kernel)


def red_mask(hsv: np.ndarray) -> np.ndarray:
    low = cv2.inRange(hsv, *RED_LOW)
    high = cv2.inRange(hsv, *RED_HIGH)
    return clean_mask(cv2.bitwise_or(low, high))


def fire_mask(hsv: np.ndarray) -> np.ndarray:
    return clean_mask(cv2.inRange(hsv, *FIRE_RANGE))


@dataclass(frozen=True)
class Blob:
    x: int
    y: int
    side: float  # pixels: the side of a square with the same area as the blob


def find_blobs(
    mask: np.ndarray,
    min_area: float,
    max_area: float = float("inf"),
    max_aspect: float = float("inf"),
) -> list[Blob]:
    """Every blob whose area is in range and whose shape is not too long and thin."""
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    blobs: list[Blob] = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < min_area or area > max_area:
            continue
        _, _, width, height = cv2.boundingRect(contour)
        if max(width, height) / max(1, min(width, height)) > max_aspect:
            continue
        moments = cv2.moments(contour)
        if moments["m00"] <= 0.0:
            continue
        blobs.append(
            Blob(
                x=int(moments["m10"] / moments["m00"]),
                y=int(moments["m01"] / moments["m00"]),
                side=sqrt(area),
            )
        )
    return sorted(blobs, key=lambda b: (b.x, b.y))


def find_blob_centres(
    mask: np.ndarray,
    min_area: float,
    max_area: float = float("inf"),
    max_aspect: float = float("inf"),
) -> list[Point]:
    """Centres of every blob whose area is in range and whose shape is not too long and thin."""
    return [(b.x, b.y) for b in find_blobs(mask, min_area, max_area, max_aspect)]


def exclude_near(points: Sequence[Point], centre: Point, radius: float) -> list[Point]:
    """The points that are farther than radius from centre."""
    return [p for p in points if hypot(p[0] - centre[0], p[1] - centre[1]) > radius]


@dataclass(frozen=True)
class Track:
    id: int
    x: int
    y: int


@dataclass
class _TrackState:
    x: int
    y: int
    seen: int = 1
    missing: int = 0


class Tracker:
    """Gives each blob a stable id and only reports it once it has been seen several frames
    in a row. A believed blob that vanishes for a few frames is still reported, so one bad
    frame cannot make a block or a fire flicker in and out of the plan."""

    def __init__(
        self,
        confirm_frames: int = CONFIRM_FRAMES,
        max_missing: int = MAX_MISSING_FRAMES,
        max_distance: float = MAX_MATCH_DISTANCE_PX,
    ) -> None:
        self._confirm_frames = confirm_frames
        self._max_missing = max_missing
        self._max_distance = max_distance
        self._states: dict[int, _TrackState] = {}
        self._next_id = 1

    def update(self, centres: Sequence[Point]) -> tuple[Track, ...]:
        pairs = sorted(
            (hypot(cx - state.x, cy - state.y), track_id, index)
            for track_id, state in self._states.items()
            for index, (cx, cy) in enumerate(centres)
        )

        matched_tracks: set[int] = set()
        matched_centres: set[int] = set()
        for distance, track_id, index in pairs:
            if distance > self._max_distance:
                break
            if track_id in matched_tracks or index in matched_centres:
                continue
            state = self._states[track_id]
            state.x, state.y = centres[index]
            state.seen += 1
            state.missing = 0
            matched_tracks.add(track_id)
            matched_centres.add(index)

        for track_id in list(self._states):
            if track_id in matched_tracks:
                continue
            self._states[track_id].missing += 1
            if self._states[track_id].missing > self._max_missing:
                del self._states[track_id]

        for index, (cx, cy) in enumerate(centres):
            if index not in matched_centres:
                self._states[self._next_id] = _TrackState(x=cx, y=cy)
                self._next_id += 1

        return tuple(
            Track(id=track_id, x=state.x, y=state.y)
            for track_id, state in sorted(self._states.items())
            if state.seen >= self._confirm_frames
        )


class SurvivorFinder:
    """Finds the pulsing survivor light, whatever colour it is.

    It keeps about a second and a half of grey pictures and looks for a small bright spot that
    keeps going dim, bright, dim. A steady light (fire, a lamp) never changes, and a hand or a
    block passing by changes only once, so neither counts. Give it a grey frame and a clock
    reading (seconds) every frame; it answers with the light's centre, or None."""

    def __init__(
        self,
        window_seconds: float = SURVIVOR_WINDOW_S,
        min_frames: int = SURVIVOR_MIN_FRAMES,
        min_swing: int = SURVIVOR_MIN_SWING,
        min_peak: int = SURVIVOR_MIN_PEAK,
        min_area: float = SURVIVOR_MIN_AREA,
        min_crossings: int = SURVIVOR_MIN_CROSSINGS,
        scale: float = SURVIVOR_SCALE,
    ) -> None:
        self._window_seconds = window_seconds
        self._min_frames = min_frames
        self._min_swing = min_swing
        self._min_peak = min_peak
        self._min_area_small = max(1, int(min_area * scale * scale))
        self._min_crossings = min_crossings
        self._scale = scale
        self._history: deque[tuple[float, np.ndarray]] = deque()

    def update(self, gray: np.ndarray, timestamp: float) -> Optional[Point]:
        small = cv2.resize(gray, None, fx=self._scale, fy=self._scale, interpolation=cv2.INTER_AREA)
        self._history.append((timestamp, small))
        while self._history and self._history[0][0] < timestamp - self._window_seconds:
            self._history.popleft()
        if len(self._history) < self._min_frames:
            return None

        stack = np.stack([frame for _, frame in self._history])
        peak = stack.max(axis=0)
        swing = peak - stack.min(axis=0)  # peak is never below the minimum, so no wrap-around
        candidates = ((swing >= self._min_swing) & (peak >= self._min_peak)).astype(np.uint8) * 255
        candidates = cv2.morphologyEx(candidates, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))

        count, _, stats, centroids = cv2.connectedComponentsWithStats(candidates)
        best: Optional[tuple[int, float, float]] = None
        for label in range(1, count):
            area = int(stats[label, cv2.CC_STAT_AREA])
            if area < self._min_area_small:
                continue
            cx, cy = centroids[label]
            if self._pulses_at(stack, int(round(cx)), int(round(cy))) and (
                best is None or area > best[0]
            ):
                best = (area, float(cx), float(cy))

        if best is None:
            return None
        return int(best[1] / self._scale), int(best[2] / self._scale)

    def _pulses_at(self, stack: np.ndarray, x: int, y: int) -> bool:
        """True if the brightness around this spot goes up and down repeatedly."""
        _, height, width = stack.shape
        patch = stack[:, max(0, y - 1) : min(height, y + 2), max(0, x - 1) : min(width, x + 2)]
        series = patch.max(axis=(1, 2)).astype(np.int16)
        low, high = int(series.min()), int(series.max())
        if high - low < self._min_swing:
            return False
        bright = series > (low + high) / 2
        crossings = int(np.count_nonzero(bright[1:] != bright[:-1]))
        return crossings >= self._min_crossings


def describe_plan(
    result: Union[PlanResult, RoutePlan], survivor: Optional[Point] = None, unit: str = ""
) -> str:
    """The plan in words. unit ("mm") is added after every position."""
    suffix = f" {unit}" if unit else ""
    lines = []
    if isinstance(result, RoutePlan):
        lines.append(result.note[0].upper() + result.note[1:] + ".")
    elif not result.order and not result.left:
        lines.append("No blocks seen.")
    elif not result.order:
        lines.append("No safe blocks to pick.")
    for number, block in enumerate(result.order, start=1):
        lines.append(f"Pick {number}: block_{block.id} at ({block.x:.0f}, {block.y:.0f}){suffix}")
    for item in result.left:
        lines.append(f"Leave block_{item.block.id}: {item.reason}")
    if survivor is not None:
        lines.append(f"Survivor light at ({survivor[0]:.0f}, {survivor[1]:.0f}){suffix}")
    return "\n".join(lines) + "\n"


def plan_signature(result: Union[PlanResult, RoutePlan], survivor_seen: bool = False) -> tuple:
    """What the plan decides, without the exact positions, so a one-pixel wobble is not news."""
    return (
        tuple(block.id for block in result.order),
        tuple((item.block.id, item.reason) for item in result.left),
        survivor_seen,
        getattr(result, "ok", True),
    )


def draw_overlay(
    frame: np.ndarray,
    result: PlanResult,
    heat_zones: Sequence[HeatZone],
    survivor: Optional[Point] = None,
    path: Sequence[tuple[float, float]] = (),
) -> np.ndarray:
    """Return a copy of the frame with heat zones, the pick order, blocks left in place, the
    survivor light and the rover's route."""
    out = frame.copy()
    if len(path) >= 2:
        points = np.array([(int(x), int(y)) for x, y in path], dtype=np.int32)
        cv2.polylines(out, [points], False, CYAN, 2)
    for zone in heat_zones:
        cv2.circle(out, (int(zone.x), int(zone.y)), int(zone.radius), ORANGE, 2)
    for number, block in enumerate(result.order, start=1):
        centre = (int(block.x), int(block.y))
        cv2.circle(out, centre, 6, GREEN, -1)
        cv2.putText(out, f"{number} block_{block.id}", (centre[0] - 15, centre[1] - 15),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, GREEN, 2)
    for item in result.left:
        centre = (int(item.block.x), int(item.block.y))
        cv2.circle(out, centre, 6, RED, -1)
        cv2.putText(out, f"block_{item.block.id} (left: {item.reason})",
                    (centre[0] - 15, centre[1] - 15), cv2.FONT_HERSHEY_SIMPLEX, 0.5, RED, 2)
    if survivor is not None:
        cv2.circle(out, survivor, 14, CYAN, 2)
        cv2.putText(out, "survivor light", (survivor[0] + 18, survivor[1] + 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, CYAN, 2)
    return out


def open_source(source: str) -> cv2.VideoCapture:
    """A webcam index such as "0", or a stream URL such as the rover camera's /stream."""
    if source.isdigit():
        index = int(source)
        if sys.platform == "win32":
            capture = cv2.VideoCapture(index, cv2.CAP_DSHOW)  # much faster start-up on Windows
        else:
            capture = cv2.VideoCapture(index)
    else:
        capture = cv2.VideoCapture(source)
    capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # keep only the newest picture, so a stream does not lag
    return capture


def parse_args(argv: Sequence[str]) -> tuple[str, bool]:
    """(video source, show the colour masks). Raises ValueError for an unknown option."""
    options = [a for a in argv if a.startswith("--")]
    unknown = [o for o in options if o not in KNOWN_OPTIONS]
    if unknown:
        raise ValueError(f"Unknown option: {unknown[0]}")
    positional = [a for a in argv if not a.startswith("--")]
    return (positional[0] if positional else "0", "--masks" in options)


@dataclass(frozen=True)
class FrameResult:
    shown: np.ndarray  # the picture with the plan drawn on it
    blocks_mask: np.ndarray
    heat_mask: np.ndarray
    result: Optional[Union[PlanResult, RoutePlan]]  # None until the block size is known
    report: Optional[str]  # text to print, set only when the plan has changed
    scene: Optional[Scene] = None  # blocks, heat and survivor in millimetres, once the scale is known
    origin: Optional[tuple[float, float]] = None  # the rover's place in the picture, in pixels
    px_per_mm: Optional[float] = None
    survivor: Optional[Point] = None  # where the survivor is in the picture, however it was found


class Pipeline:
    """Everything done to one picture: find the blocks, fire and survivor light, learn the
    scale from the 40 mm blocks, work in millimetres, plan, and draw the answer. It takes a
    picture and a clock reading (seconds) so it can be tested without a camera or a window."""

    def __init__(self, config: Optional[Config] = None, calibration: Optional[Calibration] = None) -> None:
        self._config = config if config is not None else Config()
        self._calibration = calibration  # when set, it places things on the table instead of a flat scale
        self._block_tracker = Tracker()
        self._heat_tracker = Tracker()
        self._marker_tracker = MarkerTracker()
        self._survivor_finder = SurvivorFinder()
        self._scale = ScaleEstimator(block_mm=self._config.block_mm)
        self._marker_scale = ScaleEstimator(block_mm=self._config.marker_mm)
        self._using_markers = False
        self._last_signature: Optional[tuple] = None
        self._started_at: Optional[float] = None

    @property
    def px_per_mm(self) -> Optional[float]:
        return (self._marker_scale if self._using_markers else self._scale).px_per_mm

    def _to_mm(self, point: tuple[float, float], origin: tuple[float, float], px_per_mm: float):
        if self._calibration is not None:
            return self._calibration.to_mm(point)
        return to_mm(point, origin, px_per_mm)

    def _blocks_from_markers(
        self, markers: Sequence[Marker], origin: tuple[float, float], px_per_mm: float
    ) -> tuple[Block, ...]:
        in_mm = [
            Marker(m.id, *self._to_mm((m.x, m.y), origin, px_per_mm), m.side / px_per_mm) for m in markers
        ]
        return blocks_from_markers(in_mm, self._config.rules, self._config.block_mm)

    def process(
        self, frame: np.ndarray, now: float, survivor_hint: Optional[Point] = None
    ) -> FrameResult:
        height, width = frame.shape[:2]
        origin = (width / 2.0, float(height))  # the rover is at the bottom centre of the picture
        if self._started_at is None:
            self._started_at = now
        warming_up = now - self._started_at < WARMUP_SECONDS

        blurred = cv2.GaussianBlur(frame, (5, 5), 0)
        hsv = cv2.cvtColor(blurred, cv2.COLOR_BGR2HSV)
        survivor = self._survivor_finder.update(cv2.cvtColor(blurred, cv2.COLOR_BGR2GRAY), now)
        if survivor_hint is not None:
            survivor = survivor_hint  # the operator tapped it, which beats the pulse search
        blocks_mask = red_mask(hsv)
        heat_mask = fire_mask(hsv)

        # The blocks are 40 mm cubes: how big they look sets the scale, and anything the wrong
        # size for a block is then ignored.
        # ArUco markers come first: they give each block its id, layer and weight. Red blobs
        # are the fallback while no marker is in view.
        markers = self._marker_tracker.update(find_markers(frame))
        self._using_markers = bool(markers)
        if self._using_markers:
            px_per_mm = self._marker_scale.update([m.side for m in markers])
            blobs: list[Blob] = []
        else:
            blobs = find_blobs(blocks_mask, MIN_BLOCK_AREA, MAX_BLOCK_AREA, MAX_BLOCK_ASPECT)
            px_per_mm = self._scale.update([b.side for b in blobs])
        if px_per_mm is None:
            shown = frame.copy()
            cv2.putText(shown, f"Measuring the {self._config.block_mm:g} mm blocks to set the scale...",
                        (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, CYAN, 2)
            return FrameResult(shown, blocks_mask, heat_mask, None, None)

        block_tracks = self._block_tracker.update(
            [(b.x, b.y) for b in blobs if block_size_ok(b.side, px_per_mm, self._config.block_mm)]
        )
        fire_centres = find_blob_centres(heat_mask, MIN_FIRE_AREA)
        if survivor is not None:
            fire_centres = exclude_near(fire_centres, survivor, SURVIVOR_EXCLUDE_RADIUS_PX)
        heat_tracks = self._heat_tracker.update(fire_centres)

        if self._using_markers:
            scene = scene_from_blocks(
                self._blocks_from_markers(markers, origin, px_per_mm),
                heat_tracks, survivor, origin, px_per_mm, projection=self._calibration,
            )
        else:
            scene = build_scene(
                block_tracks, heat_tracks, survivor, origin, px_per_mm, projection=self._calibration
            )
        result = decide(scene, corridor_mm=self._config.corridor_mm)

        # Report the plan only once the survivor search has had time to rule out its own light.
        report = None
        signature = plan_signature(result, survivor_seen=survivor is not None)
        if not warming_up and signature != self._last_signature:
            report = "=== PLAN CHANGED ===\n" + describe_plan(result, scene.survivor, unit="mm")
            self._last_signature = signature

        shown_result, zones = view_in_px(
            result, scene.heat_zones, origin, px_per_mm, projection=self._calibration
        )
        route_px = path_in_px(
            getattr(result, "path", ()), origin, px_per_mm, projection=self._calibration
        )
        shown = draw_overlay(frame, shown_result, zones, survivor, route_px)
        if warming_up:
            cv2.putText(shown, "Looking for the survivor light...", (10, 25),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, CYAN, 2)
        return FrameResult(
            shown, blocks_mask, heat_mask, result, report, scene, origin, px_per_mm, survivor
        )


def clock_for(source: str):
    """A video file is read much faster than it was filmed, so it gets its own frame clock.
    A camera uses the real clock."""
    if not os.path.isfile(source):
        return time.monotonic
    probe = cv2.VideoCapture(source)
    fps = probe.get(cv2.CAP_PROP_FPS) or 30.0
    probe.release()
    frames_seen = [0]

    def frame_clock() -> float:
        frames_seen[0] += 1
        return frames_seen[0] / fps

    return frame_clock


def run(source: str = "0", show_masks: bool = False) -> int:
    is_file = os.path.isfile(source)
    frames = FrameSource(
        lambda: open_source(source),
        max_failed_reads=MAX_FAILED_READS,
        max_reconnects=0 if is_file else MAX_RECONNECTS,  # a finished file is not reopened
        sleep=time.sleep,
    )
    try:
        calibration = load_calibration() if CALIBRATION_FILE.exists() else None
        pipeline = Pipeline(load_config(), calibration)
    except ValueError as error:
        print(f"Config or calibration problem: {error}", file=sys.stderr)
        return 1
    if calibration is None:
        print("No calibration.json: using a flat scale from the block size. "
              "For a camera at an angle, run calibrate.py.", flush=True)
    clock = clock_for(source)

    print("--- Rover vision and planning started (ESC to quit) ---", flush=True)
    try:
        while True:
            frame = frames.read()
            if frames.gave_up:
                break
            if frame is None:
                if cv2.waitKey(30) == 27:
                    break
                continue

            output = pipeline.process(frame, clock())
            if output.report:
                print(output.report, end="", flush=True)
            cv2.imshow(WINDOW_NAME, output.shown)
            if show_masks:
                cv2.imshow("Red mask (blocks)", output.blocks_mask)
                cv2.imshow("Fire mask (heat)", output.heat_mask)
            if cv2.waitKey(1) == 27:
                break
    finally:
        frames.close()
        cv2.destroyAllWindows()

    if frames.gave_up and not is_file:
        print(f"Lost the video source and could not reconnect: {source}", file=sys.stderr)
        return 1
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    try:
        source, show_masks = parse_args(sys.argv[1:] if argv is None else argv)
    except ValueError as error:
        print(error, file=sys.stderr)
        print("Usage: python vision.py [camera index or stream URL] [--masks]", file=sys.stderr)
        return 2
    return run(source, show_masks)


if __name__ == "__main__":
    sys.exit(main())
