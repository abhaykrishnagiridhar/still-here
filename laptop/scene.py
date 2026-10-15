"""The millimetre scene the planners work on, built from what the camera saw in pixels.

The camera program tracks blocks, heat and the survivor light in picture pixels. The planners
(planner.py and route.py) think in millimetres. This turns one into the other, picks the right
planner, and turns the answer back into pixels so it can be drawn on the picture.

Pure functions: no camera, no clock. Millimetres are measured from the rover: the rover is at
the origin, "forward" is x and "left" is y. By default pixels are turned into millimetres with a
flat scale (see scale.py). With a calibration (calibrate.py) passed as `projection`, the
calibration does it instead, which is right for a camera that looks at the table at an angle.
"""

from dataclasses import dataclass, replace
from typing import Optional, Protocol, Sequence, Union

from models import Block, HeatZone
from planner import LeftItem, PlanResult, plan
from route import RoutePlan, route
from scale import to_mm, to_px

Point = tuple[float, float]


class Projection(Protocol):
    """What a calibration offers: pixels to millimetres and back, and a circle's size in pixels."""

    def to_mm(self, point_px: Point) -> Point: ...
    def to_px(self, point_mm: Point) -> Point: ...
    def radius_px(self, centre_mm: Point, radius_mm: float) -> float: ...


def _mm(point: Point, origin_px: Point, px_per_mm: float, projection: Optional[Projection]) -> Point:
    return projection.to_mm(point) if projection is not None else to_mm(point, origin_px, px_per_mm)


def _px(point: Point, origin_px: Point, px_per_mm: float, projection: Optional[Projection]) -> Point:
    return projection.to_px(point) if projection is not None else to_px(point, origin_px, px_per_mm)

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
    projection: Optional[Projection] = None,
) -> Scene:
    """Colour cannot tell layers or weights apart yet, so every block is a light layer-1 block."""

    blocks = []
    for t in blocks_px:
        forward, left = _mm((t.x, t.y), origin_px, px_per_mm, projection)
        blocks.append(Block(id=t.id, marker_id=t.id, x=forward, y=left, layer=1))
    return scene_from_blocks(blocks, heat_px, survivor_px, origin_px, px_per_mm, heat_radius_mm, projection)


def scene_from_blocks(
    blocks_mm: Sequence[Block],
    heat_px: Sequence[Located],
    survivor_px: Optional[Point],
    origin_px: Point,
    px_per_mm: float,
    heat_radius_mm: float = HEAT_RADIUS_MM,
    projection: Optional[Projection] = None,
) -> Scene:
    """The same scene when the blocks are already in millimetres with their layer and weight,
    as they are when they come from ArUco markers."""
    zones = []
    for t in heat_px:
        forward, left = _mm((t.x, t.y), origin_px, px_per_mm, projection)
        zones.append(HeatZone(x=forward, y=left, radius=heat_radius_mm))
    survivor = None if survivor_px is None else _mm(survivor_px, origin_px, px_per_mm, projection)
    return Scene(blocks=tuple(blocks_mm), heat_zones=tuple(zones), survivor=survivor)


def decide(
    scene: Scene, start: Point = ROVER_MM, corridor_mm: Optional[float] = None
) -> Union[PlanResult, RoutePlan]:
    """With no survivor found yet, list every block that may be removed. Once the survivor is
    known, find the way to it and remove only the blocks that are in the way. corridor_mm is
    how wide a path the buggy needs; left out, the route planner's default is used."""
    if scene.survivor is None:
        return plan(scene.blocks, scene.heat_zones)
    extra = {} if corridor_mm is None else {"corridor": corridor_mm}
    return route(scene.blocks, scene.heat_zones, start, scene.survivor, **extra)


def view_in_px(
    result: Union[PlanResult, RoutePlan],
    heat_zones_mm: Sequence[HeatZone],
    origin_px: Point,
    px_per_mm: float,
    projection: Optional[Projection] = None,
) -> tuple[PlanResult, tuple[HeatZone, ...]]:
    """The same answer with every position back in picture pixels, ready to draw."""

    def block_px(block: Block) -> Block:
        x, y = _px((block.x, block.y), origin_px, px_per_mm, projection)
        return replace(block, x=x, y=y)

    shown = PlanResult(
        order=tuple(block_px(b) for b in result.order),
        left=tuple(LeftItem(block=block_px(i.block), reason=i.reason) for i in result.left),
    )
    zones = []
    for z in heat_zones_mm:
        x, y = _px((z.x, z.y), origin_px, px_per_mm, projection)
        radius = z.radius * px_per_mm if projection is None else projection.radius_px((z.x, z.y), z.radius)
        zones.append(HeatZone(x=x, y=y, radius=radius))
    return shown, tuple(zones)


def path_in_px(
    path_mm: Optional[Sequence[Point]],
    origin_px: Point,
    px_per_mm: float,
    projection: Optional[Projection] = None,
) -> list[Point]:
    """The rover's route as picture points; nothing to draw when there is no route."""
    if not path_mm:
        return []
    return [_px(p, origin_px, px_per_mm, projection) for p in path_mm]
