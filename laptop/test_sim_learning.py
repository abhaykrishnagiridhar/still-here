"""The software rover with a hidden truth: its real width is more than the planner was told.

A block the planner thought was safely beside the path can then be brushed on the way to the survivor. The
rover reports that as a `bump`, which is what the laptop learns from (experience.py).
"""

from models import Block
from sim_rover import SimRover

DT = 0.05
PICK = {"id": 1, "action": "pick", "x": 150, "y": 0, "z": 20}
DROP = {"id": 2, "action": "drop", "x": 100, "y": -172, "z": 20}
SURVIVOR = (300.0, 0.0)


def run(rover, seconds):
    sent = []
    for i in range(round(seconds / DT)):
        if i % 10 == 0:
            sent += rover.handle({"type": "ping", "t": rover.t})
        sent += rover.step(DT)
    return sent


def codes(messages):
    return [m["code"] for m in messages if m["type"] == "event"]


def bumps(messages):
    return [m["detail"] for m in messages if m["type"] == "event" and m["code"] == "bump"]


def run_plan(rover):
    rover.handle({"type": "plan", "plan_id": 1, "steps": [PICK, DROP]})
    rover.handle({"type": "plan_start", "plan_id": 1})
    return run(rover, 30)


def make(side_y, half_width=135.0):
    blocks = [Block(1, 1, 150.0, 0.0, 1), Block(5, 5, 110.0, side_y, 1)]
    return SimRover(blocks, survivor=SURVIVOR, buggy_half_width_mm=half_width)


def test_a_block_closer_than_the_real_half_width_is_bumped_on_the_way_to_the_survivor():
    sent = run_plan(make(side_y=145.0))

    assert bumps(sent) == ["block_5"]


def test_the_bump_is_reported_before_the_plan_is_called_finished():
    sent = run_plan(make(side_y=145.0))
    events = codes(sent)

    assert events.index("bump") < events.index("plan_finished")


def test_a_block_farther_than_the_real_half_width_is_not_bumped():
    sent = run_plan(make(side_y=170.0))

    assert bumps(sent) == []
    assert "plan_finished" in codes(sent)


def test_a_block_beyond_the_survivor_is_never_in_the_way():
    rover = SimRover(
        [Block(1, 1, 150.0, 0.0, 1), Block(5, 5, 340.0, 0.0, 1)], survivor=SURVIVOR, buggy_half_width_mm=135.0
    )

    assert bumps(run_plan(rover)) == []


def test_a_block_far_to_the_side_is_never_bumped():
    sent = run_plan(make(side_y=400.0))

    assert bumps(sent) == []


def test_without_a_hidden_width_nothing_is_ever_bumped():
    rover = SimRover([Block(1, 1, 150.0, 0.0, 1), Block(5, 5, 110.0, 145.0, 1)], survivor=SURVIVOR)

    assert bumps(run_plan(rover)) == []


def test_only_the_nearest_block_is_named():
    blocks = [Block(1, 1, 150.0, 0.0, 1), Block(5, 5, 110.0, 145.0, 1), Block(6, 6, 200.0, -125.0, 1)]
    rover = SimRover(blocks, survivor=SURVIVOR, buggy_half_width_mm=135.0)

    assert bumps(run_plan(rover)) == ["block_6"]


def test_reset_world_puts_every_block_back_and_the_arm_home():
    rover = make(side_y=145.0)
    run_plan(rover)
    assert rover.blocks[1].block.x != 150.0 or rover.blocks[1].block.y != 0.0

    out = rover.handle({"type": "reset_world"})

    assert rover.blocks[1].block.x == 150.0 and rover.blocks[1].block.y == 0.0
    assert rover.blocks[1].z == 20.0
    assert rover.carrying is None
    assert not rover.plan_running
    assert codes(out) == ["world_reset"]


def test_after_a_reset_the_same_plan_can_run_again():
    rover = make(side_y=145.0)
    run_plan(rover)
    rover.handle({"type": "reset_world"})

    sent = run_plan(rover)

    assert bumps(sent) == ["block_5"]
    assert [m["ok"] for m in sent if m["type"] == "step_done"] == [True, True]


def test_a_reset_stops_a_plan_that_is_running():
    rover = make(side_y=145.0)
    rover.handle({"type": "plan", "plan_id": 1, "steps": [PICK, DROP]})
    rover.handle({"type": "plan_start", "plan_id": 1})
    run(rover, 1)
    assert rover.plan_running

    rover.handle({"type": "reset_world"})

    assert not rover.plan_running
