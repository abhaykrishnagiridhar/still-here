"""Route search: which blocks must be removed so the rover can reach the survivor.

The floor is a grid. Every block "covers" the cells around it, far enough out that a rover
corridor_mm wide cannot pass through. Each cell is then one of:
- blocked, when a block that must stay covers it (heavy, load-bearing, near heat, or holding
  up a block that stays, as decided by planner.plan), or when it lies inside a heat zone;
- costly, when only removable blocks cover it. Entering it costs one removal per block, so the
  search removes as few blocks as it can, and goes around when the detour is shorter than
  removal_cost.
The removable blocks along the cheapest path are the ones to remove, top first. Everything
else is left, with the reason.

Units are millimetres, in the arm frame (docs/protocol.md). A pure function: no camera, no
rover, no clock. Run it again on a new snapshot to re-plan.
"""

import heapq
from dataclasses import dataclass
from math import ceil, floor, hypot
from typing import Optional, Sequence

from models import Block, HeatZone
from planner import LeftItem, plan

Point = tuple[float, float]
Bounds = tuple[float, float, float, float]  # x_min, y_min, x_max, y_max
Cell = tuple[int, int]

# Block size matches config.example.toml. The corridor is an assumption: measure the real rover.
DEFAULT_BLOCK_SIZE_MM = 40.0  # the blocks are 40 mm cubes
DEFAULT_CORRIDOR_MM = 60.0  # width the rover needs to drive through
DEFAULT_CELL_MM = 10.0  # grid resolution
DEFAULT_REMOVAL_COST_MM = 100.0  # removing one block is worth this much extra driving

_EPSILON = 1e-9
_NEIGHBOURS = tuple(
    (di, dj, hypot(di, dj)) for di in (-1, 0, 1) for dj in (-1, 0, 1) if (di, dj) != (0, 0)
)


@dataclass(frozen=True)
class RoutePlan:
    ok: bool
    order: tuple[Block, ...]  # blocks to remove, in the order to remove them
    left: tuple[LeftItem, ...]  # blocks that stay, each with the reason
    path: tuple[Point, ...]  # where the rover drives, from the start to the survivor
    note: str


@dataclass(frozen=True)
class _Grid:
    x0: float
    y0: float
    cell: float
    cols: int
    rows: int

    def snap(self, point: Point) -> Cell:
        i = round((point[0] - self.x0) / self.cell)
        j = round((point[1] - self.y0) / self.cell)
        return (min(max(i, 0), self.cols - 1), min(max(j, 0), self.rows - 1))

    def centre(self, cell: Cell) -> Point:
        return (self.x0 + cell[0] * self.cell, self.y0 + cell[1] * self.cell)

    def contains(self, cell: Cell) -> bool:
        return 0 <= cell[0] < self.cols and 0 <= cell[1] < self.rows

    def cells_near(self, x: float, y: float, reach: float) -> list[Cell]:
        """Every cell whose centre is within reach (a square) of the point, inside the grid."""
        i0 = max(0, ceil((x - reach - self.x0) / self.cell - _EPSILON))
        i1 = min(self.cols - 1, floor((x + reach - self.x0) / self.cell + _EPSILON))
        j0 = max(0, ceil((y - reach - self.y0) / self.cell - _EPSILON))
        j1 = min(self.rows - 1, floor((y + reach - self.y0) / self.cell + _EPSILON))
        return [(i, j) for i in range(i0, i1 + 1) for j in range(j0, j1 + 1)]


def _validate(block_size: float, corridor: float, cell: float, removal_cost: float) -> None:
    if block_size <= 0:
        raise ValueError("block_size must be greater than zero")
    if corridor < 0:
        raise ValueError("corridor must not be negative")
    if cell <= 0:
        raise ValueError("cell must be greater than zero")
    if removal_cost < 0:
        raise ValueError("removal_cost must not be negative")


def _default_bounds(
    blocks: Sequence[Block], heat_zones: Sequence[HeatZone], start: Point, goal: Point, margin: float
) -> Bounds:
    xs = [start[0], goal[0]] + [b.x for b in blocks]
    ys = [start[1], goal[1]] + [b.y for b in blocks]
    for zone in heat_zones:
        xs += [zone.x - zone.radius, zone.x + zone.radius]
        ys += [zone.y - zone.radius, zone.y + zone.radius]
    return (min(xs) - margin, min(ys) - margin, max(xs) + margin, max(ys) + margin)


def _make_grid(bounds: Bounds, cell: float) -> _Grid:
    x_min, y_min, x_max, y_max = bounds
    cols = floor((x_max - x_min) / cell + _EPSILON) + 1
    rows = floor((y_max - y_min) / cell + _EPSILON) + 1
    return _Grid(x0=x_min, y0=y_min, cell=cell, cols=cols, rows=rows)


def _cover_map(grid: _Grid, blocks: Sequence[Block], reach: float) -> dict[Cell, tuple[int, ...]]:
    covering: dict[Cell, list[int]] = {}
    for block in blocks:
        for cell in grid.cells_near(block.x, block.y, reach):
            covering.setdefault(cell, []).append(block.id)
    return {cell: tuple(sorted(ids)) for cell, ids in covering.items()}


def _heat_cells(grid: _Grid, heat_zones: Sequence[HeatZone], corridor: float) -> set[Cell]:
    hot: set[Cell] = set()
    for zone in heat_zones:
        reach = zone.radius + corridor / 2
        for cell in grid.cells_near(zone.x, zone.y, reach):
            cx, cy = grid.centre(cell)
            if hypot(cx - zone.x, cy - zone.y) <= reach + _EPSILON:
                hot.add(cell)
    return hot


def _cheapest_path(
    grid: _Grid,
    cover: dict[Cell, tuple[int, ...]],
    blocked: set[Cell],
    start: Cell,
    goal: Cell,
    removal_cost: float,
) -> Optional[list[Cell]]:
    """Dijkstra over the grid. Entering a cell costs its length plus one removal per block
    that covers it and did not cover the cell we came from."""
    if start in blocked or goal in blocked:
        return None

    best = {start: removal_cost * len(cover.get(start, ()))}
    came_from: dict[Cell, Cell] = {}
    queue = [(best[start], start)]
    while queue:
        cost, here = heapq.heappop(queue)
        if cost > best.get(here, float("inf")):
            continue
        if here == goal:
            break
        for di, dj, length in _NEIGHBOURS:
            there = (here[0] + di, here[1] + dj)
            if not grid.contains(there) or there in blocked:
                continue
            if di and dj and ((here[0] + di, here[1]) in blocked or (here[0], here[1] + dj) in blocked):
                continue  # no squeezing diagonally between two obstacles
            new_blocks = set(cover.get(there, ())) - set(cover.get(here, ()))
            new_cost = cost + length * grid.cell + removal_cost * len(new_blocks)
            if new_cost < best.get(there, float("inf")):
                best[there] = new_cost
                came_from[there] = here
                heapq.heappush(queue, (new_cost, there))

    if goal not in best:
        return None
    path = [goal]
    while path[-1] != start:
        path.append(came_from[path[-1]])
    path.reverse()
    return path


def _with_what_rests_on(ids: set[int], removable: dict[int, Block]) -> set[int]:
    """Blocks resting on a block to remove must be removed before it, wherever they sit."""
    closure = set(ids)
    pending = list(ids)
    while pending:
        for resting in removable[pending.pop()].supports:
            if resting in removable and resting not in closure:
                closure.add(resting)
                pending.append(resting)
    return closure


def _left_items(
    blocks: Sequence[Block], stays: dict[int, str], removed: set[int]
) -> tuple[LeftItem, ...]:
    return tuple(
        LeftItem(block=b, reason=stays.get(b.id, "not in the way"))
        for b in sorted(blocks, key=lambda b: b.id)
        if b.id not in removed
    )


def route(
    blocks: Sequence[Block],
    heat_zones: Sequence[HeatZone],
    start: Point,
    goal: Point,
    *,
    bounds: Optional[Bounds] = None,
    block_size: float = DEFAULT_BLOCK_SIZE_MM,
    corridor: float = DEFAULT_CORRIDOR_MM,
    cell: float = DEFAULT_CELL_MM,
    removal_cost: float = DEFAULT_REMOVAL_COST_MM,
) -> RoutePlan:
    _validate(block_size, corridor, cell, removal_cost)

    scene = plan(blocks, heat_zones)  # which blocks may be removed at all, and why not
    removable = {b.id: b for b in scene.order}
    stays = {item.block.id: item.reason for item in scene.left}

    if bounds is None:
        bounds = _default_bounds(blocks, heat_zones, start, goal, margin=block_size + 2 * corridor)
    grid = _make_grid(bounds, cell)

    cover = _cover_map(grid, blocks, reach=block_size / 2 + corridor / 2)
    blocked = _heat_cells(grid, heat_zones, corridor)
    blocked.update(c for c, ids in cover.items() if any(i not in removable for i in ids))

    cells = _cheapest_path(grid, cover, blocked, grid.snap(start), grid.snap(goal), removal_cost)
    if cells is None:
        return RoutePlan(
            ok=False,
            order=(),
            left=_left_items(blocks, stays, removed=set()),
            path=(),
            note="no route to the survivor: every way is blocked by blocks that must stay",
        )

    on_path = {block_id for c in cells for block_id in cover.get(c, ())}
    to_remove = _with_what_rests_on(on_path, removable)
    order = tuple(b for b in scene.order if b.id in to_remove)  # the planner's top-first order

    waypoints = [grid.centre(c) for c in cells]
    waypoints[0], waypoints[-1] = (float(start[0]), float(start[1])), (float(goal[0]), float(goal[1]))
    note = "the path is already clear" if not order else f"clear after removing {len(order)} block(s)"
    return RoutePlan(
        ok=True,
        order=order,
        left=_left_items(blocks, stays, removed=to_remove),
        path=tuple(waypoints),
        note=note,
    )
