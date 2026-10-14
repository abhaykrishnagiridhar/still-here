"""Pick order for clearing blocks. A pure function: no camera, no rover, no clock.

The rules, in plain words:
- Top blocks come first. A block is only picked once nothing rests on it.
- A heavy block, a load-bearing block and a block near heat are left where they are.
- A block that holds up a block which stays is left too.

Units are millimetres and coordinates are in the arm frame, see docs/protocol.md.
"""

from dataclasses import dataclass
from math import hypot
from typing import Optional, Sequence

from models import Block, HeatZone


@dataclass(frozen=True)
class LeftItem:
    block: Block
    reason: str


@dataclass(frozen=True)
class PlanResult:
    order: tuple[Block, ...]
    left: tuple[LeftItem, ...]


def _fixed_reason(block: Block, heat_zones: Sequence[HeatZone]) -> Optional[str]:
    """Why a block must stay no matter what is around it, or None if it may be picked."""
    if block.weight_class == "heavy":
        return "heavy block"
    if block.load_bearing:
        return "load-bearing"
    if any(hypot(block.x - zone.x, block.y - zone.y) <= zone.radius for zone in heat_zones):
        return "near heat"
    return None


def plan(blocks: Sequence[Block], heat_zones: Sequence[HeatZone] = ()) -> PlanResult:
    present = {block.id for block in blocks}
    fixed = {block.id: _fixed_reason(block, heat_zones) for block in blocks}

    removed: set[int] = set()
    order: list[Block] = []
    waiting = [block for block in blocks if fixed[block.id] is None]

    # Each pass picks every block that has nothing left resting on it, highest layer first.
    while True:
        ready = sorted(
            (b for b in waiting if all(s in removed for s in b.supports if s in present)),
            key=lambda b: (-b.layer, b.id),
        )
        if not ready:
            break
        order.extend(ready)
        removed.update(b.id for b in ready)
        waiting = [b for b in waiting if b.id not in removed]

    left = []
    for block in sorted((b for b in blocks if b.id not in removed), key=lambda b: b.id):
        reason = fixed[block.id]
        if reason is None:
            holding = sorted(s for s in block.supports if s in present and s not in removed)
            reason = f"holds up block {holding[0]}, which stays"
        left.append(LeftItem(block=block, reason=reason))

    return PlanResult(order=tuple(order), left=tuple(left))
