"""Did the claw really pick the block up?

The arm cannot feel whether it holds anything (hobby servos report no position or force), so the
camera is the check. After the rover says a pick is done, the block must no longer be sitting where
it was. If the camera keeps seeing it there, the claw closed on nothing.

The arm passing in front of the block can hide it for a moment, and a block seen again restarts
nothing it should not: the wait only counts pictures in a row that show the block in its old place.
Pure logic with an explicit clock, so it is tested without a camera.
"""

from math import hypot
from typing import Optional, Sequence

from models import Block

IN_PLACE_TOL_MM = 15.0  # tracking noise is a few mm: farther than this means the block really moved
HOLD_S = 1.5  # how long the block must stay in its old place before it counts as an empty grab


class GripWatch:
    def __init__(self, baseline: Sequence[Block], *, hold_s: float = HOLD_S, tol_mm: float = IN_PLACE_TOL_MM) -> None:
        if hold_s < 0 or tol_mm <= 0:
            raise ValueError("the wait must not be negative and the tolerance must be greater than zero")
        self._start = {b.id: b for b in baseline}
        self._hold_s = hold_s
        self._tol = tol_mm
        self._claimed: set[int] = set()  # blocks the rover says it is carrying
        self._since: dict[int, float] = {}  # block id -> when it was first seen in its old place

    def picked(self, block_id: int, now: float) -> None:
        """The rover reported this block picked up."""
        if block_id in self._start:
            self._claimed.add(block_id)

    def released(self, block_id: int) -> None:
        """The rover reported this block put down: it is no longer judged."""
        self._claimed.discard(block_id)
        self._since.pop(block_id, None)

    def check(self, blocks: Sequence[Block], now: float) -> Optional[str]:
        """A reason the grab failed, or None. Call with every new picture."""
        current = {b.id: b for b in blocks}
        for block_id in sorted(self._claimed):
            start, seen = self._start[block_id], current.get(block_id)
            if seen is None or hypot(seen.x - start.x, seen.y - start.y) > self._tol:
                self._since.pop(block_id, None)  # lifted out of view, or carried away: a good grab
                continue
            first = self._since.setdefault(block_id, now)
            if now - first >= self._hold_s:
                return f"block_{block_id} is still where it was after the rover said it picked it up"
        return None
