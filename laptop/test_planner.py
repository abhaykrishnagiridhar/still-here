import dataclasses

import pytest

from models import Block, HeatZone
from planner import plan


def block(block_id, layer=1, x=0.0, y=0.0, **kwargs):
    return Block(id=block_id, marker_id=block_id, x=x, y=y, layer=layer, **kwargs)


def picked_ids(result):
    return [b.id for b in result.order]


def left_ids(result):
    return [item.block.id for item in result.left]


def reason_for(result, block_id):
    return next(item.reason for item in result.left if item.block.id == block_id)


def test_empty_scene_gives_an_empty_plan():
    result = plan([])

    assert result.order == ()
    assert result.left == ()


def test_two_block_stack_picks_the_top_block_first():
    bottom = block(1, layer=1, supports=(2,))
    top = block(2, layer=2)

    result = plan([bottom, top])

    assert picked_ids(result) == [2, 1]
    assert result.left == ()


def test_the_order_does_not_depend_on_the_input_order():
    bottom = block(1, layer=1, supports=(2,))
    top = block(2, layer=2)

    assert plan([bottom, top]) == plan([top, bottom])


def test_a_block_is_never_picked_while_something_rests_on_it():
    low = block(1, layer=1, supports=(2,))
    middle = block(2, layer=2, supports=(3,))
    high = block(3, layer=3)

    result = plan([low, middle, high])

    assert picked_ids(result) == [3, 2, 1]


def test_a_heavy_block_is_left_in_place():
    heavy = block(1, weight_class="heavy")
    light = block(2)

    result = plan([heavy, light])

    assert picked_ids(result) == [2]
    assert left_ids(result) == [1]
    assert reason_for(result, 1) == "heavy block"


def test_a_load_bearing_block_is_left_in_place():
    result = plan([block(1, load_bearing=True), block(2)])

    assert picked_ids(result) == [2]
    assert reason_for(result, 1) == "load-bearing"


def test_a_block_under_a_block_that_stays_is_left_too():
    bottom = block(1, layer=1, supports=(2,))
    heavy_top = block(2, layer=2, weight_class="heavy")

    result = plan([bottom, heavy_top])

    assert picked_ids(result) == []
    assert sorted(left_ids(result)) == [1, 2]
    assert "2" in reason_for(result, 1)
    assert "stays" in reason_for(result, 1)


def test_a_block_near_heat_is_left_alone_and_a_far_one_is_picked():
    heat = HeatZone(x=100.0, y=100.0, radius=50.0)
    near = block(1, x=120.0, y=100.0)
    far = block(2, x=400.0, y=400.0)

    result = plan([near, far], [heat])

    assert picked_ids(result) == [2]
    assert reason_for(result, 1) == "near heat"


def test_a_block_exactly_on_the_edge_of_a_heat_zone_counts_as_near():
    heat = HeatZone(x=0.0, y=0.0, radius=50.0)
    on_the_edge = block(1, x=50.0, y=0.0)

    result = plan([on_the_edge], [heat])

    assert left_ids(result) == [1]


def test_support_ids_that_are_not_in_the_scene_are_ignored():
    result = plan([block(1, supports=(99,))])

    assert picked_ids(result) == [1]


def test_blocks_on_the_same_layer_are_ordered_by_id():
    result = plan([block(5), block(3), block(4)])

    assert picked_ids(result) == [3, 4, 5]


def test_every_block_is_either_picked_or_left_never_both():
    blocks = [
        block(1, layer=1, supports=(2,)),
        block(2, layer=2, weight_class="heavy"),
        block(3),
        block(4, load_bearing=True),
    ]

    result = plan(blocks)

    assert sorted(picked_ids(result) + left_ids(result)) == [1, 2, 3, 4]
    assert set(picked_ids(result)).isdisjoint(left_ids(result))


def test_planning_does_not_change_its_input_and_the_result_is_frozen():
    blocks = [block(1, layer=1, supports=(2,)), block(2, layer=2)]
    before = list(blocks)

    result = plan(blocks)

    assert blocks == before
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.order = ()
