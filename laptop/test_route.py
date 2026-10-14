"""Tests for the route search: which blocks must go so the rover can reach the survivor.

Scene used throughout (millimetres, arm frame): a 400 x 220 floor, the rover at the left
edge and the survivor at the right edge, both at y = 80. A "wall" is a row of blocks across
the floor at x = 200 that closes it completely, so the rover cannot go around.
"""

import dataclasses
from math import hypot

import pytest

from models import Block, HeatZone
from route import DEFAULT_BLOCK_SIZE_MM, DEFAULT_CORRIDOR_MM, route

START = (20.0, 80.0)
GOAL = (380.0, 80.0)
BOUNDS = (0.0, 0.0, 400.0, 220.0)
BLOCK_SIZE = 30.0
CORRIDOR = 60.0
CELL = 10.0
REACH = BLOCK_SIZE / 2 + CORRIDOR / 2  # how close the path may come to a block's centre

WALL_YS = (20.0, 80.0, 140.0, 200.0)


def block(block_id, x=200.0, y=80.0, layer=1, **kwargs):
    return Block(id=block_id, marker_id=block_id, x=x, y=y, layer=layer, **kwargs)


def wall(heavy_ys=(), x=200.0):
    """A closed wall: one block per y in WALL_YS, ids 1 to 4, some of them heavy."""
    return [
        block(i + 1, x=x, y=y, weight_class="heavy" if y in heavy_ys else "light")
        for i, y in enumerate(WALL_YS)
    ]


def go(blocks, heat=(), start=START, goal=GOAL, **kwargs):
    sizes = {"block_size": BLOCK_SIZE, "corridor": CORRIDOR, "cell": CELL}
    sizes.update(kwargs)
    return route(blocks, heat, start, goal, bounds=BOUNDS, **sizes)


def picked(result):
    return [b.id for b in result.order]


def left_reason(result, block_id):
    return next(item.reason for item in result.left if item.block.id == block_id)


def path_stays_clear_of(result, blocks):
    return all(
        not (abs(px - b.x) <= REACH and abs(py - b.y) <= REACH)
        for b in blocks
        for px, py in result.path
    )


def test_an_empty_floor_gives_a_direct_path_and_nothing_to_remove():
    result = go([])

    assert result.ok
    assert result.order == ()
    assert result.left == ()
    assert result.path[0] == START
    assert result.path[-1] == GOAL


def test_a_block_that_can_be_walked_around_is_left_alone():
    only = block(1)

    result = go([only])

    assert result.ok
    assert result.order == ()
    assert left_reason(result, 1) == "not in the way"
    assert path_stays_clear_of(result, [only])


def test_a_closed_wall_costs_exactly_the_block_on_the_straight_line():
    result = go(wall())

    assert result.ok
    assert picked(result) == [2]  # the block at y = 80
    assert {item.block.id for item in result.left} == {1, 3, 4}


def test_a_heavy_block_on_the_line_makes_the_route_cross_at_the_nearest_light_block():
    result = go(wall(heavy_ys=(80.0, 140.0, 200.0)))

    assert result.ok
    assert picked(result) == [1]  # the light block at y = 20
    assert left_reason(result, 2) == "heavy block"


def test_a_wall_of_only_heavy_blocks_has_no_route():
    result = go(wall(heavy_ys=WALL_YS))

    assert not result.ok
    assert result.order == ()
    assert result.path == ()
    assert "no route" in result.note
    assert left_reason(result, 2) == "heavy block"


def test_a_stack_in_the_only_gap_is_removed_top_first():
    gap = [
        block(1, y=80.0, layer=1, supports=(2,)),
        block(2, y=80.0, layer=2),
        block(3, y=20.0, weight_class="heavy"),
        block(4, y=140.0, weight_class="heavy"),
        block(5, y=200.0, weight_class="heavy"),
    ]

    result = go(gap)

    assert result.ok
    assert picked(result) == [2, 1]


def test_a_survivor_buried_under_a_stack_needs_the_whole_stack_removed():
    buried = [
        block(1, x=GOAL[0], y=GOAL[1], layer=1, supports=(2,)),
        block(2, x=GOAL[0], y=GOAL[1], layer=2),
    ]

    result = go(buried)

    assert result.ok
    assert picked(result) == [2, 1]


def test_a_heavy_block_on_the_survivor_means_no_route():
    result = go([block(1, x=GOAL[0], y=GOAL[1], weight_class="heavy")])

    assert not result.ok
    assert "no route" in result.note


def test_the_path_goes_around_a_heat_zone():
    heat = HeatZone(x=200.0, y=80.0, radius=50.0)

    result = go([], [heat])

    assert result.ok
    assert all(hypot(px - heat.x, py - heat.y) > heat.radius for px, py in result.path)


def test_a_heat_zone_that_fills_the_floor_means_no_route():
    heat = HeatZone(x=200.0, y=110.0, radius=300.0)

    assert not go([], [heat]).ok


def test_a_blocker_that_something_rests_on_takes_that_block_down_first():
    # Block 5 rests on block 2 but sits away from the path. It still has to go before block 2.
    scene = wall() + [block(5, x=350.0, y=200.0, layer=2)]
    scene[1] = dataclasses.replace(scene[1], supports=(5,))

    result = go(scene)

    assert picked(result) == [5, 2]


def test_a_block_that_holds_up_a_block_that_stays_cannot_be_removed():
    scene = [
        block(1, y=20.0, weight_class="heavy"),
        block(2, y=80.0, layer=1, supports=(5,)),
        block(3, y=140.0, weight_class="heavy"),
        block(4, y=200.0, weight_class="heavy"),
        block(5, y=80.0, layer=2, weight_class="heavy"),
    ]

    result = go(scene)

    assert not result.ok
    assert "5" in left_reason(result, 2)
    assert "stays" in left_reason(result, 2)


def test_moving_the_blocking_block_away_changes_the_answer():
    before = go(wall())
    scene = wall()
    scene[1] = dataclasses.replace(scene[1], x=330.0, y=200.0)  # block 2 is nudged off the line
    after = go(scene)

    assert picked(before) == [2]
    assert after.ok
    assert after.order == ()  # the wall now has a gap, so nothing needs to be removed


def test_the_answer_does_not_depend_on_the_order_of_the_input():
    scene = wall(heavy_ys=(80.0,))

    assert go(scene) == go(list(reversed(scene)))


def test_routing_does_not_change_its_input_and_the_result_is_frozen():
    scene = wall()
    before = list(scene)

    result = go(scene)

    assert scene == before
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.ok = False


def test_the_default_bounds_still_let_the_path_go_around_a_block():
    result = route([block(1)], (), START, GOAL, block_size=BLOCK_SIZE, corridor=CORRIDOR, cell=CELL)

    assert result.ok
    assert result.order == ()


def test_the_default_block_is_40_mm_wide():
    only = block(1)

    result = route([only], (), START, GOAL, bounds=BOUNDS, cell=CELL)  # default block and corridor

    reach = 40.0 / 2 + DEFAULT_CORRIDOR_MM / 2
    assert DEFAULT_BLOCK_SIZE_MM == 40.0
    assert result.ok
    assert all(
        not (abs(px - only.x) <= reach and abs(py - only.y) <= reach) for px, py in result.path
    )


def test_default_bounds_make_room_for_a_heat_zone_that_sticks_out_past_the_points():
    heat = HeatZone(x=200.0, y=80.0, radius=120.0)  # reaches beyond the start and goal rows

    result = route([], [heat], START, GOAL, block_size=BLOCK_SIZE, corridor=CORRIDOR, cell=CELL)

    assert result.ok
    assert all(hypot(px - heat.x, py - heat.y) > heat.radius for px, py in result.path)


@pytest.mark.parametrize(
    "bad",
    [{"cell": 0.0}, {"cell": -5.0}, {"corridor": -1.0}, {"block_size": 0.0}, {"removal_cost": -1.0}],
)
def test_nonsense_sizes_are_rejected(bad):
    with pytest.raises(ValueError):
        go([], **bad)
