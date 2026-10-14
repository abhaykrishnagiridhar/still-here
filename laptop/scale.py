"""Pixels to millimetres, learned from the blocks themselves.

Every block is a 40 mm cube, so how many pixels wide a block looks says how many pixels make
a millimetre. That scale also tells a real block from something the wrong size, such as a
table edge or a speck.

Camera-frame millimetres, until the calibration tool exists: the origin is where the rover
sits (the bottom centre of the picture), "forward" is up the picture and "left" is left in
the picture. This assumes a camera looking more or less straight ahead, so the scale is
only approximate across a deep scene.
"""

from collections import deque
from statistics import median
from typing import Optional, Sequence

BLOCK_MM = 40.0  # the blocks are 40 mm cubes

# A block can look somewhat smaller or bigger than average, because nearer ones look bigger.
MIN_BLOCK_SIZE_RATIO = 0.5
MAX_BLOCK_SIZE_RATIO = 1.8

Point = tuple[float, float]


class ScaleEstimator:
    """Keeps the typical on-screen side of a block over the last few frames, and turns it into
    pixels per millimetre. The median of each frame and of the window means a stray table edge
    or a missed block does not throw it off."""

    def __init__(self, block_mm: float = BLOCK_MM, window: int = 45, min_samples: int = 5) -> None:
        if block_mm <= 0:
            raise ValueError("block_mm must be greater than zero")
        if window < 1:
            raise ValueError("window must be at least 1")
        if min_samples < 1:
            raise ValueError("min_samples must be at least 1")
        self._block_mm = block_mm
        self._min_samples = min_samples
        self._samples: deque[float] = deque(maxlen=window)

    def update(self, side_lengths_px: Sequence[float]) -> Optional[float]:
        """Feed the side length, in pixels, of every block seen in this frame."""
        if side_lengths_px:
            self._samples.append(float(median(side_lengths_px)))
        return self.px_per_mm

    @property
    def px_per_mm(self) -> Optional[float]:
        if len(self._samples) < self._min_samples:
            return None
        return float(median(self._samples)) / self._block_mm


def block_size_ok(
    side_px: float,
    px_per_mm: Optional[float],
    block_mm: float = BLOCK_MM,
    low: float = MIN_BLOCK_SIZE_RATIO,
    high: float = MAX_BLOCK_SIZE_RATIO,
) -> bool:
    """True if a blob this many pixels wide could be a block. Anything is allowed until the
    scale is known."""
    if px_per_mm is None:
        return True
    expected = px_per_mm * block_mm
    return low * expected <= side_px <= high * expected


def _check_scale(px_per_mm: float) -> None:
    if px_per_mm <= 0:
        raise ValueError("px_per_mm must be greater than zero")


def to_mm(point_px: Point, origin_px: Point, px_per_mm: float) -> Point:
    """(forward, left) in millimetres from the rover, for a point in the picture."""
    _check_scale(px_per_mm)
    forward = (origin_px[1] - point_px[1]) / px_per_mm
    left = (origin_px[0] - point_px[0]) / px_per_mm
    return (forward, left)


def to_px(point_mm: Point, origin_px: Point, px_per_mm: float) -> Point:
    """The picture position of a (forward, left) point in millimetres. The inverse of to_mm."""
    _check_scale(px_per_mm)
    forward, left = point_mm
    return (origin_px[0] - left * px_per_mm, origin_px[1] - forward * px_per_mm)
