"""Does the scene still match what the approved plan assumed?

When a plan is approved, the blocks are where the camera saw them. While the rover works, this
compares each new picture with that starting scene and reports a reason when it no longer fits:

- a block the rover has not touched has MOVED more than a small tolerance (it was nudged, or
  fell), which can change what is safe to pick or what holds what up
- a block the rover has not touched is NO LONGER SEEN
- a NEW block has appeared somewhere other than the drop spot

Blocks the rover has started on (the one it is carrying, the ones it has moved) are expected to
change and are ignored. A change has to last a little while before it counts, because the arm
passing in front of a neighbour can hide it for a moment: a disappearance has to last longer
than a movement. Pure logic with an explicit clock, so it is tested without a camera.
"""

from math import hypot
from typing import Optional, Sequence

from models import Block

MOVE_TOL_MM = 15.0  # tracking noise is a few mm: this is clearly a real movement
MOVED_HOLD_S = 1.0
MISSING_HOLD_S = 3.0  # longer: the arm and the carried block can hide a neighbour
NEW_HOLD_S = 1.5
DROP_RADIUS_MM = 80.0  # blocks put down at the drop spot are expected to appear around it


class SceneWatch:
    def __init__(
        self,
        baseline: Sequence[Block],
        *,
        drop_mm: tuple[float, float],
        move_tol_mm: float = MOVE_TOL_MM,
        moved_hold_s: float = MOVED_HOLD_S,
        missing_hold_s: float = MISSING_HOLD_S,
        new_hold_s: float = NEW_HOLD_S,
        drop_radius_mm: float = DROP_RADIUS_MM,
    ) -> None:
        if move_tol_mm <= 0 or min(moved_hold_s, missing_hold_s, new_hold_s) < 0:
            raise ValueError("the tolerance must be greater than zero and the waits must not be negative")
        self._baseline = {b.id: b for b in baseline}
        self._drop = drop_mm
        self._tol = move_tol_mm
        self._holds = {"moved": moved_hold_s, "missing": missing_hold_s, "new": new_hold_s}
        self._drop_radius = drop_radius_mm
        self._since: dict[tuple[str, int], float] = {}  # (kind, block id) -> when it first looked wrong

    def check(self, blocks: Sequence[Block], handled: set[int], now: float) -> Optional[str]:
        """A reason the scene no longer matches the plan, or None. Call with every new picture."""
        current = {b.id: b for b in blocks}
        wrong: dict[tuple[str, int], str] = {}

        for block_id, start in self._baseline.items():
            if block_id in handled:
                continue
            seen = current.get(block_id)
            if seen is None:
                wrong[("missing", block_id)] = f"block_{block_id} is no longer seen"
                continue
            distance = hypot(seen.x - start.x, seen.y - start.y)
            if distance > self._tol:
                wrong[("moved", block_id)] = f"block_{block_id} moved {distance:.0f} mm"

        for block_id, seen in current.items():
            if block_id in self._baseline or block_id in handled:
                continue
            if hypot(seen.x - self._drop[0], seen.y - self._drop[1]) <= self._drop_radius:
                continue
            wrong[("new", block_id)] = f"a new block (block_{block_id}) appeared at ({seen.x:.0f}, {seen.y:.0f}) mm"

        # What looked wrong and now looks right starts again from nothing.
        self._since = {key: since for key, since in self._since.items() if key in wrong}
        for key in wrong:
            self._since.setdefault(key, now)

        for kind in ("moved", "missing", "new"):
            for key, reason in wrong.items():
                if key[0] == kind and now - self._since[key] >= self._holds[kind]:
                    return reason
        return None
