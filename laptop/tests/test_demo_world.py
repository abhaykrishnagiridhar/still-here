"""The scene the Blender twin builds for the autonomy demo must be one the real planner can solve."""

from math import hypot

from demo_world import (
    BLOCKS,
    FIRE_MM,
    FRAME_MM,
    HEAT_RADIUS_MM,
    PATH_BLOCK_IDS,
    SIDE_BLOCK_IDS,
    SURVIVOR_MM,
)
from models import HeatZone
from operator_core import DROP_POINT_MM
from route import DEFAULT_CORRIDOR_MM, route
from sim_rover import BLOCK_SIZE, solve_pose

BLOCK_BY_ID = {block.id: block for block in BLOCKS}


def test_every_block_in_the_path_is_within_the_arms_reach():
    for block_id in PATH_BLOCK_IDS:
        block = BLOCK_BY_ID[block_id]
        assert solve_pose(block.x, block.y, BLOCK_SIZE / 2, 90.0) is not None, block


def test_blocks_are_separated_enough_for_the_camera_to_see_them_as_separate():
    blocks = list(BLOCKS)
    for i, a in enumerate(blocks):
        for b in blocks[i + 1 :]:
            gap = max(abs(a.x - b.x), abs(a.y - b.y)) - BLOCK_SIZE
            assert gap >= 8.0, (a, b)


def test_everything_is_inside_the_top_down_picture():
    x_min, y_min, x_max, y_max = FRAME_MM
    margin = BLOCK_SIZE / 2
    points = [(b.x, b.y) for b in BLOCKS] + [SURVIVOR_MM, FIRE_MM[:2], DROP_POINT_MM]
    for x, y in points:
        assert x_min + margin <= x <= x_max - margin and y_min + margin <= y <= y_max - margin, (x, y)


def test_the_path_blocks_are_in_the_corridor_and_the_side_blocks_are_not():
    half = DEFAULT_CORRIDOR_MM / 2 + BLOCK_SIZE / 2
    assert all(abs(BLOCK_BY_ID[i].y) < half for i in PATH_BLOCK_IDS)
    assert all(abs(BLOCK_BY_ID[i].y) >= half for i in SIDE_BLOCK_IDS)


def test_the_fire_is_clear_of_blocks_and_the_drop_point():
    fx, fy, radius = FIRE_MM
    for block in BLOCKS:
        assert hypot(block.x - fx, block.y - fy) > radius + BLOCK_SIZE
    assert hypot(DROP_POINT_MM[0] - fx, DROP_POINT_MM[1] - fy) > radius + BLOCK_SIZE


def test_the_real_route_planner_removes_the_path_blocks_and_leaves_the_rest():
    fx, fy, _ = FIRE_MM
    result = route(
        list(BLOCKS),
        [HeatZone(fx, fy, HEAT_RADIUS_MM)],
        (0.0, 0.0),
        SURVIVOR_MM,
        bounds=FRAME_MM,
        corridor=DEFAULT_CORRIDOR_MM,
    )

    assert result.ok
    assert sorted(block.id for block in result.order) == sorted(PATH_BLOCK_IDS)


def test_the_fire_is_far_enough_off_the_path_for_the_route_to_pass_it():
    _, fy, _ = FIRE_MM

    assert abs(fy) > HEAT_RADIUS_MM + DEFAULT_CORRIDOR_MM / 2


def test_every_drop_slot_is_clear_of_the_fire():
    from operator_core import DROP_SLOTS_MM

    fx, fy, radius = FIRE_MM
    for x, y in DROP_SLOTS_MM:
        assert hypot(x - fx, y - fy) > HEAT_RADIUS_MM + BLOCK_SIZE


# ---- the learning loop's geometry ---------------------------------------------------------------

from demo_world import BUGGY_TRUE_HALF_WIDTH_MM


def _removed_with_corridor(corridor):
    fx, fy, _ = FIRE_MM
    result = route(
        list(BLOCKS),
        [HeatZone(fx, fy, HEAT_RADIUS_MM)],
        (0.0, 0.0),
        SURVIVOR_MM,
        bounds=FRAME_MM,
        corridor=corridor,
    )
    assert result.ok
    return sorted(block.id for block in result.order)


def test_the_planner_is_told_less_than_the_buggys_real_width():
    assert BUGGY_TRUE_HALF_WIDTH_MM > DEFAULT_CORRIDOR_MM / 2


def test_the_side_block_is_one_the_real_buggy_would_brush_but_the_planner_leaves():
    side = BLOCK_BY_ID[SIDE_BLOCK_IDS[0]]
    edge_gap = abs(side.y) - BLOCK_SIZE / 2

    assert edge_gap >= DEFAULT_CORRIDOR_MM / 2  # the planner thinks the buggy clears it
    assert edge_gap < BUGGY_TRUE_HALF_WIDTH_MM  # the real buggy does not


def test_one_learned_widening_step_makes_the_planner_remove_the_side_block_too():
    one_step_each_side_mm = 10.0

    widened = DEFAULT_CORRIDOR_MM + 2 * one_step_each_side_mm

    assert _removed_with_corridor(widened) == sorted((*PATH_BLOCK_IDS, *SIDE_BLOCK_IDS))


def test_one_learned_step_is_enough_for_the_real_buggy():
    side = BLOCK_BY_ID[SIDE_BLOCK_IDS[0]]
    learned_half_width = DEFAULT_CORRIDOR_MM / 2 + 10.0

    assert abs(side.y) - BLOCK_SIZE / 2 < learned_half_width  # so the planner now counts it as in the way
