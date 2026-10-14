"""The millimetre scene the planners work on, built from what the camera saw in pixels.

The camera program tracks blocks, heat and the survivor light in picture pixels. The planners
(planner.py and route.py) think in millimetres. This turns one into the other, picks the right
planner, and turns the answer back into pixels so it can be drawn on the picture.

Pure functions: no camera, no clock. Camera-frame millimetres until the calibration tool
exists: the rover is at the origin, "forward" is x and "left" is y (see scale.py).
"""

from dataclasses import dataclass, replace
from typing import Optional, Protocol, Sequence, Union

from models import Block, HeatZone
from planner import LeftItem, PlanResult, plan
from route import RoutePlan, route
from scale import to_mm, to_px

Point = tuple[float, float]

# An assumption: measure how close a block can safely sit to a heat source.
HEAT_RADIUS_MM = 100.0

ROVER_MM: Point = (0.0, 0.0)  # the rover is the origin of the camera-frame millimetres


class Located(Protocol):
    """Anything the tracker reports: an id and a picture position."""

    @property
    def id(self) -> int: ...
    @property
    def x(self) -> float: ...
    @property
    def y(self) -> float: ...


@dataclass(frozen=True)
class Scene:
    blocks: tuple[Block, ...]
    heat_zones: tuple[HeatZone, ...]
    survivor: Optional[Point]


def build_scene(
    blocks_px: Sequence[Located],
    heat_px: Sequence[Located],
    survivor_px: Optional[Point],
    origin_px: Point,
    px_per_mm: float,
    heat_radius_mm: float = HEAT_RADIUS_MM,
) -> Scene:
    """Colour cannot tell layers or weights apart yet, so every block is a light layer-1 block."""

    def in_mm(x: float, y: float) -> Point:
        return to_mm((x, y), origin_px, px_per_mm)

    blocks = []
    for t in blocks_px:
        forward, left = in_mm(t.x, t.y)
        blocks.append(Block(id=t.id, marker_id=t.id, x=forward, y=left, layer=1))
    zones = []
    for t in heat_px:
        forward, left = in_mm(t.x, t.y)
        zones.append(HeatZone(x=forward, y=left, radius=heat_radius_mm))
    survivor = None if survivor_px is None else in_mm(survivor_px[0], survivor_px[1])
    return Scene(blocks=tuple(blocks), heat_zones=tuple(zones), survivor=survivor)


def decide(scene: Scene, start: Point = ROVER_MM) -> Union[PlanResult, RoutePlan]:
    """With no survivor found yet, list every block that may be removed. Once the survivor is
    known, find the way to it and remove only the blocks that are in the way."""
    if scene.survivor is None:
        return plan(scene.blocks, scene.heat_zones)
    return route(scene.blocks, scene.heat_zones, start, scene.survivor)


def view_in_px(
    result: Union[PlanResult, RoutePlan],
    heat_zones_mm: Sequence[HeatZone],
    origin_px: Point,
    px_per_mm: float,
) -> tuple[PlanResult, tuple[HeatZone, ...]]:
    """The same answer with every position back in picture pixels, ready to draw."""

    def block_px(block: Block) -> Block:
        x, y = to_px((block.x, block.y), origin_px, px_per_mm)
        return replace(block, x=x, y=y)

    shown = PlanResult(
        order=tuple(block_px(b) for b in result.order),
        left=tuple(LeftItem(block=block_px(i.block), reason=i.reason) for i in result.left),
    )
    zones = []
    for z in heat_zones_mm:
        x, y = to_px((z.x, z.y), origin_px, px_per_mm)
        zones.append(HeatZone(x=x, y=y, radius=z.radius * px_per_mm))
    return shown, tuple(zones)


def path_in_px(
    path_mm: Optional[Sequence[Point]], origin_px: Point, px_per_mm: float
) -> list[Point]:
    """The rover's route as picture points; nothing to draw when there is no route."""
    if not path_mm:
        return []
    return [to_px(p, origin_px, px_per_mm) for p in path_mm]
