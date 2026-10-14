"""Tests for turning what the camera sees (pixels) into the millimetre scene the planners use."""

import dataclasses
from dataclasses import dataclass

import pytest

from models import Block
from planner import PlanResult
from route import RoutePlan
from scene import HEAT_RADIUS_MM, build_scene, decide, path_in_px, view_in_px

ORIGIN = (320.0, 480.0)  # bottom centre of a 640 x 480 picture: the rover
SCALE = 1.5  # pixels per millimetre: a 40 mm block is 60 pixels wide


@dataclass(frozen=True)
class Seen:
    """Anything the tracker reports: an id and a picture position."""

    id: int
    x: float
    y: float


def px_for(forward_mm, left_mm):
    """Where a point forward_mm ahead and left_mm to the left lands in the picture."""
    return (ORIGIN[0] - left_mm * SCALE, ORIGIN[1] - forward_mm * SCALE)


def seen(item_id, forward_mm, left_mm):
    x, y = px_for(forward_mm, left_mm)
    return Seen(id=item_id, x=x, y=y)


def scene_of(blocks=(), heat=(), survivor_mm=None):
    survivor_px = None if survivor_mm is None else px_for(*survivor_mm)
    return build_scene(blocks, heat, survivor_px, ORIGIN, SCALE)


def test_a_block_ahead_of_the_rover_becomes_a_forward_millimetre_position():
    scene = scene_of([seen(7, 100.0, 0.0)])

    block = scene.blocks[0]
    assert block.id == 7
    assert (round(block.x), round(block.y)) == (100, 0)
    assert block.layer == 1
    assert block.weight_class == "light"


def test_left_in_the_picture_is_a_positive_left_position():
    scene = scene_of([seen(1, 50.0, 40.0)])

    assert (round(scene.blocks[0].x), round(scene.blocks[0].y)) == (50, 40)


def test_a_heat_source_becomes_a_zone_with_a_radius_in_millimetres():
    scene = scene_of(heat=[seen(1, 200.0, -30.0)])

    zone = scene.heat_zones[0]
    assert (round(zone.x), round(zone.y)) == (200, -30)
    assert zone.radius == HEAT_RADIUS_MM


def test_the_survivor_is_converted_and_a_missing_survivor_stays_missing():
    assert [round(v) for v in scene_of(survivor_mm=(300.0, 20.0)).survivor] == [300, 20]
    assert scene_of().survivor is None


def test_without_a_survivor_the_old_planner_picks_every_removable_block():
    scene = scene_of([seen(1, 100.0, 0.0), seen(2, 150.0, 80.0)])

    result = decide(scene)

    assert isinstance(result, PlanResult)
    assert sorted(b.id for b in result.order) == [1, 2]


def test_with_a_survivor_a_block_that_can_be_driven_around_is_left_alone():
    scene = scene_of([seen(1, 150.0, 0.0)], survivor_mm=(300.0, 0.0))

    result = decide(scene)

    assert isinstance(result, RoutePlan)
    assert result.ok
    assert result.order == ()


def test_a_block_on_the_survivor_has_to_be_removed():
    scene = scene_of([seen(1, 300.0, 0.0)], survivor_mm=(300.0, 0.0))

    result = decide(scene)

    assert [b.id for b in result.order] == [1]


def test_the_view_in_pixels_puts_everything_back_where_the_camera_saw_it():
    scene = scene_of([seen(1, 100.0, 0.0), seen(2, 200.0, 60.0)], heat=[seen(1, 250.0, -50.0)])
    result = decide(scene)

    shown, zones = view_in_px(result, scene.heat_zones, ORIGIN, SCALE)

    positions = {b.id: (round(b.x), round(b.y)) for b in shown.order}
    assert positions == {
        1: tuple(round(v) for v in px_for(100.0, 0.0)),
        2: tuple(round(v) for v in px_for(200.0, 60.0)),
    }
    assert (round(zones[0].x), round(zones[0].y)) == tuple(round(v) for v in px_for(250.0, -50.0))
    assert zones[0].radius == pytest.approx(HEAT_RADIUS_MM * SCALE)


def test_the_view_keeps_the_reasons_for_blocks_left_in_place():
    heat = seen(1, 100.0, 0.0)
    scene = scene_of([seen(1, 100.0, 0.0)], heat=[heat])
    result = decide(scene)

    shown, _ = view_in_px(result, scene.heat_zones, ORIGIN, SCALE)

    assert [item.reason for item in shown.left] == ["near heat"]


def test_the_route_is_drawn_back_in_pixels():
    scene = scene_of(survivor_mm=(300.0, 0.0))
    result = decide(scene)

    drawn = path_in_px(result.path, ORIGIN, SCALE)

    assert len(drawn) == len(result.path)
    assert tuple(round(v) for v in drawn[0]) == tuple(round(v) for v in ORIGIN)


def test_a_result_without_a_route_has_no_path_to_draw():
    assert path_in_px(None, ORIGIN, SCALE) == []
    assert path_in_px((), ORIGIN, SCALE) == []


def test_building_and_deciding_do_not_change_the_inputs_and_the_scene_is_frozen():
    blocks = [seen(1, 100.0, 0.0)]
    before = list(blocks)

    scene = scene_of(blocks)
    decide(scene)

    assert blocks == before
    with pytest.raises(dataclasses.FrozenInstanceError):
        scene.survivor = (0.0, 0.0)
    assert isinstance(scene.blocks[0], Block)
