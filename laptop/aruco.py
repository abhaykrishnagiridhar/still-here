"""ArUco markers on the blocks, and the config file that says what each marker id means.

Each block carries one marker (dictionary 4x4_50, ids 0 to 49). The id says everything the
camera cannot see by colour:
- an id in `top_marker_ids` is a top-layer block, any other id is a bottom-layer block
- an id in `heavy_marker_ids` is a heavy block, which is never picked up
- a top block sitting on a bottom block makes the bottom block "hold it up", so the planner
  picks the top one first and never the bottom one while a kept block rests on it

Positions here are plain numbers in whatever unit the caller uses: pixels from `find_markers`,
millimetres once they have been converted for `blocks_from_markers`.
"""

import tomllib
from dataclasses import dataclass
from math import hypot
from pathlib import Path
from typing import Optional, Sequence

import cv2
import numpy as np

from models import Block

DICTIONARY = cv2.aruco.DICT_4X4_50
LAPTOP_DIR = Path(__file__).resolve().parent
EXAMPLE_CONFIG = LAPTOP_DIR / "config.example.toml"
LOCAL_CONFIG = LAPTOP_DIR / "config.toml"  # a copy of the example with the team's own values

DEFAULT_BLOCK_MM = 40.0
BUGGY_LENGTH_RANGE_MM = (450.0, 500.0)  # the official length of the buggy
SUPPORT_REACH_RATIO = 1.5  # a top block rests on the nearest bottom block within this many block widths
MAX_MISSING_FRAMES = 10  # frames a marker may vanish (motion blur, a hand in the way) and be kept


@dataclass(frozen=True)
class Marker:
    id: int
    x: float
    y: float
    side: float  # length of one side of the printed square


@dataclass(frozen=True)
class BlockRules:
    top_ids: frozenset[int] = frozenset()
    heavy_ids: frozenset[int] = frozenset()


@dataclass(frozen=True)
class Config:
    """Every setting from config.toml. The defaults are the same as config.example.toml."""

    rover_host: str = "still-here.local"  # the rover announces this name on the network
    ws_port: int = 81
    stream_path: str = "/stream"
    block_mm: float = DEFAULT_BLOCK_MM
    marker_mm: float = 30.0  # printed side of the marker on a block face
    heavy_marker_ids: tuple[int, ...] = (9,)
    top_marker_ids: tuple[int, ...] = (5, 6, 7, 8)
    pulse_hz: float = 1.5
    max_shift_mm: float = 5.0
    max_rotation_deg: float = 10.0
    buggy_breadth_mm: float = 200.0  # the buggy's official width
    buggy_length_mm: float = 475.0  # official: between 450 and 500
    clearance_mm: float = 20.0  # spare room each side when driving between blocks

    @property
    def corridor_mm(self) -> float:
        """How wide a clear path the buggy needs."""
        return self.buggy_breadth_mm + 2 * self.clearance_mm

    @property
    def rules(self) -> BlockRules:
        return BlockRules(
            top_ids=frozenset(self.top_marker_ids), heavy_ids=frozenset(self.heavy_marker_ids)
        )


# --- the config file ------------------------------------------------------------------


def _number(table: dict, key: str, default: float) -> float:
    value = table.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ValueError(f"{key} must be a number greater than zero, got {value!r}")
    return float(value)


def _ids(table: dict, key: str, default: tuple[int, ...]) -> tuple[int, ...]:
    value = table.get(key, list(default))
    ok = isinstance(value, list) and all(
        isinstance(i, int) and not isinstance(i, bool) and i >= 0 for i in value
    )
    if not ok:
        raise ValueError(f"{key} must be a list of whole numbers, got {value!r}")
    return tuple(value)


def _text(table: dict, key: str, default: str) -> str:
    value = table.get(key, default)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} must be some text, got {value!r}")
    return value


def _whole(table: dict, key: str, default: int) -> int:
    value = table.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{key} must be a whole number greater than zero, got {value!r}")
    return value


def load_config(path: Optional[Path] = None) -> Config:
    """Read the settings. With no path: config.toml if it exists, else config.example.toml.
    A path that does not exist gives the defaults. A file with a mistake in it raises
    ValueError naming the file and the setting."""
    if path is None:
        path = LOCAL_CONFIG if LOCAL_CONFIG.exists() else EXAMPLE_CONFIG
    path = Path(path)
    if not path.exists():
        return Config()
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        raise ValueError(f"{path.name} is not valid TOML: {error}") from error
    defaults = Config()
    rover, blocks = data.get("rover", {}), data.get("blocks", {})
    light, test = data.get("survivor_light", {}), data.get("test", {})
    buggy = data.get("buggy", {})
    try:
        config = Config(
            rover_host=_text(rover, "host", defaults.rover_host),
            ws_port=_whole(rover, "ws_port", defaults.ws_port),
            stream_path=_text(rover, "stream_path", defaults.stream_path),
            block_mm=_number(blocks, "size_mm", defaults.block_mm),
            marker_mm=_number(blocks, "marker_mm", defaults.marker_mm),
            heavy_marker_ids=_ids(blocks, "heavy_marker_ids", defaults.heavy_marker_ids),
            top_marker_ids=_ids(blocks, "top_marker_ids", defaults.top_marker_ids),
            pulse_hz=_number(light, "pulse_hz", defaults.pulse_hz),
            max_shift_mm=_number(test, "max_shift_mm", defaults.max_shift_mm),
            max_rotation_deg=_number(test, "max_rotation_deg", defaults.max_rotation_deg),
            buggy_breadth_mm=_number(buggy, "breadth_mm", defaults.buggy_breadth_mm),
            buggy_length_mm=_number(buggy, "length_mm", defaults.buggy_length_mm),
            clearance_mm=_number(buggy, "clearance_mm", defaults.clearance_mm),
        )
    except ValueError as error:
        raise ValueError(f"{path.name}: {error}") from error
    low, high = BUGGY_LENGTH_RANGE_MM
    if not low <= config.buggy_length_mm <= high:
        raise ValueError(
            f"{path.name}: length_mm ({config.buggy_length_mm:g}) must be between {low:g} and {high:g}, "
            "the official length of the buggy"
        )
    if config.marker_mm > config.block_mm:
        raise ValueError(
            f"{path.name}: marker_mm ({config.marker_mm:g}) must not be bigger than "
            f"size_mm ({config.block_mm:g}), the marker has to fit on the block"
        )
    return config


# --- finding markers ------------------------------------------------------------------

_detector: Optional[cv2.aruco.ArucoDetector] = None


def _get_detector() -> cv2.aruco.ArucoDetector:
    global _detector
    if _detector is None:
        _detector = cv2.aruco.ArucoDetector(
            cv2.aruco.getPredefinedDictionary(DICTIONARY), cv2.aruco.DetectorParameters()
        )
    return _detector


def find_markers(frame: np.ndarray) -> tuple[Marker, ...]:
    """Every marker in the picture, sorted by id. If one id shows twice, the larger one wins."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
    corners, ids, _ = _get_detector().detectMarkers(gray)
    if ids is None:
        return ()
    found: dict[int, Marker] = {}
    for square, marker_id in zip(corners, ids.ravel(), strict=True):
        points = square.reshape(4, 2)
        centre = points.mean(axis=0)
        side = float(np.mean([hypot(*(points[i] - points[(i + 1) % 4])) for i in range(4)]))
        marker = Marker(int(marker_id), float(centre[0]), float(centre[1]), side)
        if marker.id not in found or marker.side > found[marker.id].side:
            found[marker.id] = marker
    return tuple(found[i] for i in sorted(found))


class MarkerTracker:
    """Keeps a marker for a few frames after it was last seen, so a blur or a passing hand
    does not make a block vanish from the plan."""

    def __init__(self, max_missing: int = MAX_MISSING_FRAMES) -> None:
        self._max_missing = max_missing
        self._kept: dict[int, tuple[Marker, int]] = {}  # id -> (marker, frames missed)

    def update(self, markers: Sequence[Marker]) -> tuple[Marker, ...]:
        seen = {m.id: m for m in markers}
        kept = {i: (m, 0) for i, m in seen.items()}
        for marker_id, (marker, missed) in self._kept.items():
            if marker_id not in seen and missed + 1 <= self._max_missing:
                kept[marker_id] = (marker, missed + 1)
        self._kept = kept
        return tuple(kept[i][0] for i in sorted(kept))


# --- what a marker means --------------------------------------------------------------


def blocks_from_markers(
    markers: Sequence[Marker], rules: BlockRules, block_mm: float = DEFAULT_BLOCK_MM
) -> tuple[Block, ...]:
    """Blocks from markers whose positions are already in millimetres."""
    bottom = [m for m in markers if m.id not in rules.top_ids]
    reach = block_mm * SUPPORT_REACH_RATIO
    # A marker on a top block sits about a block height above the marker of the block under
    # it, so it is matched to the nearest bottom block, not only one directly beneath it.
    rests_on: dict[int, list[int]] = {m.id: [] for m in bottom}
    for top in (m for m in markers if m.id in rules.top_ids):
        nearest = min(bottom, key=lambda b: hypot(b.x - top.x, b.y - top.y), default=None)
        if nearest is not None and hypot(nearest.x - top.x, nearest.y - top.y) <= reach:
            rests_on[nearest.id].append(top.id)
    blocks = []
    for marker in markers:
        blocks.append(
            Block(
                id=marker.id,
                marker_id=marker.id,
                x=marker.x,
                y=marker.y,
                layer=2 if marker.id in rules.top_ids else 1,
                weight_class="heavy" if marker.id in rules.heavy_ids else "light",
                supports=tuple(sorted(rests_on.get(marker.id, ()))),
            )
        )
    return tuple(blocks)
