import dataclasses

import pytest

from models import Block, Plan, PlanStep


def test_block_defaults_to_light_and_not_load_bearing():
    block = Block(id=1, marker_id=7, x=100.0, y=0.0, layer=2)

    assert block.weight_class == "light"
    assert block.load_bearing is False
    assert block.supports == ()


def test_block_is_immutable():
    block = Block(id=1, marker_id=7, x=100.0, y=0.0, layer=2)

    with pytest.raises(dataclasses.FrozenInstanceError):
        block.x = 5.0


def test_plan_keeps_step_order():
    steps = (
        PlanStep(id=1, action="pick", x=100.0, y=0.0, z=40.0),
        PlanStep(id=2, action="drop", x=0.0, y=150.0, z=20.0),
    )

    plan = Plan(plan_id=1, steps=steps)

    assert [s.id for s in plan.steps] == [1, 2]
