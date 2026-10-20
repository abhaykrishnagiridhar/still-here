"""The software rover: same messages as docs/protocol.md, no hardware."""

from math import pi

import pytest

import sim_rover
from models import Block, HeatZone
from sim_rover import (
    HOME_POSE,
    LINK_TIMEOUT_S,
    SimRover,
    arm_tip,
    clamp,
    clamp_pose,
    solve_pose,
)

DT = 0.05
PICK = {"id": 1, "action": "pick", "x": 150, "y": 0, "z": 20}
DROP = {"id": 2, "action": "drop", "x": 100, "y": -80, "z": 20}


def run(rover, seconds, ping=True):
    """Advance time, pinging every 0.5 s like the laptop does; return every message sent back."""
    sent = []
    for i in range(round(seconds / DT)):
        if ping and i % 10 == 0:
            sent += rover.handle({"type": "ping", "t": rover.t})
        sent += rover.step(DT)
    return sent


def codes(messages):
    return [m["code"] for m in messages if m["type"] == "event"]


def step_results(messages):
    return [(m["step_id"], m["ok"], m["reason"]) for m in messages if m["type"] == "step_done"]


def start_plan(rover, steps, plan_id=1):
    out = rover.handle({"type": "plan", "plan_id": plan_id, "steps": steps})
    out += rover.handle({"type": "plan_start", "plan_id": plan_id})
    return out


# --- geometry -------------------------------------------------------------------------


def test_clamp_keeps_a_value_inside_its_range():
    assert clamp(5, 0, 3) == 3
    assert clamp(-5, 0, 3) == 0
    assert clamp(2, 0, 3) == 2


def test_clamp_pose_keeps_every_joint_inside_its_limits():
    pose = clamp_pose({"base": 500, "shoulder": -50, "elbow": 400, "gripper": 200})

    assert pose == {"base": 90.0, "shoulder": 0.0, "elbow": 135.0, "gripper": 90.0}


def test_a_pose_solved_for_a_point_puts_the_tip_there():
    pose = solve_pose(150.0, 40.0, 80.0, 90.0)

    x, y, z = arm_tip(pose)

    assert (round(x, 3), round(y, 3), round(z, 3)) == (150.0, 40.0, 80.0)


def test_a_point_beyond_the_arms_reach_has_no_pose():
    assert solve_pose(500.0, 0.0, 60.0, 90.0) is None


def test_a_point_on_the_arm_base_has_no_pose():
    assert solve_pose(0.0, 0.0, 60.0, 90.0) is None


def test_arm_frame_and_world_frame_convert_back_and_forth():
    rover = SimRover()
    rover.x, rover.y, rover.heading = 300.0, -100.0, pi / 3

    ax, ay = rover.to_arm_frame(450.0, 20.0)
    wx, wy = rover.to_world(ax, ay)

    assert (round(wx, 6), round(wy, 6)) == (450.0, 20.0)


# --- incoming messages ----------------------------------------------------------------


def test_an_unknown_message_type_is_ignored():
    assert SimRover().handle({"type": "something_new"}) == []


def test_a_message_with_no_type_is_ignored():
    assert SimRover().handle({}) == []


def test_mode_switches_between_manual_and_auto_only():
    rover = SimRover()

    rover.handle({"type": "mode", "mode": "auto"})
    assert rover.mode == "auto"

    rover.handle({"type": "mode", "mode": "turbo"})
    assert rover.mode == "auto"


def test_driving_forward_moves_the_rover_forward():
    rover = SimRover()
    rover.handle({"type": "drive", "left": 1.0, "right": 1.0})

    run(rover, 1.0)

    assert rover.x == pytest.approx(200.0, rel=0.05)
    assert rover.y == pytest.approx(0.0, abs=1.0)


def test_wheel_speeds_are_clamped_to_full_speed():
    rover = SimRover()

    rover.handle({"type": "drive", "left": 9.0, "right": -9.0})

    assert rover.wheels == (1.0, -1.0)


def test_unreadable_wheel_speeds_leave_the_wheels_alone():
    rover = SimRover()
    rover.handle({"type": "drive", "left": 0.5, "right": 0.5})

    rover.handle({"type": "drive", "left": "fast", "right": 0.5})

    assert rover.wheels == (0.5, 0.5)


def test_a_faster_right_wheel_turns_the_rover_left():
    rover = SimRover()
    rover.handle({"type": "drive", "left": -0.5, "right": 0.5})

    run(rover, 1.0)

    assert rover.heading > 0.5


def test_the_arm_moves_towards_a_pose_no_faster_than_the_servo_rate():
    rover = SimRover()
    rover.handle({"type": "arm_pose", "base": 90, "shoulder": 60, "elbow": -90, "gripper": 90, "speed": 1.0})

    rover.step(0.5)

    assert rover.pose["base"] == pytest.approx(sim_rover.SERVO_RATE_DPS * 0.5)


def test_the_arm_reaches_the_pose_it_was_told():
    rover = SimRover()
    rover.handle({"type": "arm_pose", "base": 45, "shoulder": 30, "elbow": -60, "gripper": 0})

    run(rover, 3.0)

    assert rover.pose == pytest.approx({"base": 45, "shoulder": 30, "elbow": -60, "gripper": 0})


def test_a_slow_arm_move_is_slower():
    fast, slow = SimRover(), SimRover()
    fast.handle({"type": "arm_pose", "base": 80, "speed": 1.0})
    slow.handle({"type": "arm_pose", "base": 80, "speed": 0.25})

    fast.step(0.3)
    slow.step(0.3)

    assert slow.pose["base"] < fast.pose["base"]


def test_an_arm_pose_outside_the_limits_is_clamped():
    rover = SimRover()

    rover.handle({"type": "arm_pose", "base": 500, "shoulder": 60, "elbow": -90, "gripper": 90})
    run(rover, 4.0)

    assert rover.pose["base"] == pytest.approx(90.0)


def test_an_unreadable_arm_pose_leaves_the_arm_alone():
    rover = SimRover()

    rover.handle({"type": "arm_pose", "base": "left"})
    run(rover, 1.0)

    assert rover.pose == pytest.approx(HOME_POSE)


# --- plans ----------------------------------------------------------------------------


def test_a_good_plan_is_stored():
    out = SimRover().handle({"type": "plan", "plan_id": 3, "steps": [PICK, DROP]})

    assert out == [{"type": "event", "code": "plan_stored", "detail": "2 steps"}]


def test_a_plan_missing_fields_is_refused():
    out = SimRover().handle({"type": "plan", "plan_id": 3, "steps": [{"id": 1}]})

    assert codes(out) == ["bad_plan"]


def test_a_plan_with_an_unknown_action_is_refused():
    out = SimRover().handle({"type": "plan", "plan_id": 3, "steps": [{**PICK, "action": "juggle"}]})

    assert codes(out) == ["bad_plan"]


def test_starting_a_plan_that_was_never_stored_is_refused():
    assert codes(SimRover().handle({"type": "plan_start", "plan_id": 9})) == ["bad_plan"]


def test_starting_a_plan_with_the_wrong_id_is_refused():
    rover = SimRover()
    rover.handle({"type": "plan", "plan_id": 1, "steps": [PICK]})

    assert codes(rover.handle({"type": "plan_start", "plan_id": 2})) == ["bad_plan"]


def test_the_state_message_carries_the_stored_plan_id():
    rover = SimRover()
    assert rover.state_message()["plan_id"] is None

    rover.handle({"type": "plan", "plan_id": 7, "steps": [PICK]})

    assert rover.state_message()["plan_id"] == 7


def test_a_pick_and_drop_moves_the_block_and_finishes_the_plan():
    rover = SimRover([Block(1, 1, 150, 0, 1)])
    sent = start_plan(rover, [PICK, DROP])

    sent += run(rover, 20)

    assert step_results(sent) == [(1, True, ""), (2, True, "")]
    assert codes(sent)[-1] == "plan_finished"
    moved = rover.blocks[1].block
    assert (round(moved.x), round(moved.y)) == (100, -80)
    assert rover.carrying is None
    assert rover.state_message()["status"] == "idle"
    assert rover.pose == pytest.approx(HOME_POSE, abs=1.0)


def test_the_block_follows_the_gripper_while_it_is_carried():
    rover = SimRover([Block(1, 1, 150, 0, 1)])
    start_plan(rover, [PICK, DROP])

    seen_lifted = False
    for _ in range(round(20 / DT)):
        rover.step(DT)
        if rover.carrying == 1:
            tx, ty, tz = rover.tip_world()
            assert rover.blocks[1].z == pytest.approx(tz, abs=2.0)  # trails the tip by one tick
            seen_lifted = seen_lifted or tz > 40
    assert seen_lifted


def test_the_status_says_running_during_a_plan_and_holding_when_carrying_after_an_abort():
    rover = SimRover([Block(1, 1, 150, 0, 1)])
    start_plan(rover, [PICK, DROP])
    assert rover.state_message()["status"] == "running"

    while rover.carrying is None:
        run(rover, 0.5)
    rover.handle({"type": "abort"})

    assert rover.state_message()["status"] == "holding"


def test_picking_where_there_is_no_block_fails_the_step_and_the_plan_goes_on():
    rover = SimRover()
    sent = start_plan(rover, [PICK, DROP])

    sent += run(rover, 20)

    assert step_results(sent)[0] == (1, False, "no block under the gripper")
    assert codes(sent)[-1] == "plan_finished"


def test_a_step_out_of_the_arms_reach_fails_as_unreachable():
    rover = SimRover()
    sent = start_plan(rover, [{**PICK, "x": 900}])

    sent += run(rover, 2)

    assert step_results(sent) == [(1, False, "unreachable")]
    assert codes(sent)[-1] == "plan_finished"


def test_an_empty_plan_finishes_without_a_step():
    rover = SimRover()
    rover.handle({"type": "plan", "plan_id": 1, "steps": []})

    rover.handle({"type": "plan_start", "plan_id": 1})

    assert rover.state_message()["status"] == "idle"


def test_driving_and_arm_commands_are_ignored_while_a_plan_runs():
    rover = SimRover([Block(1, 1, 150, 0, 1)])
    start_plan(rover, [PICK, DROP])

    rover.handle({"type": "drive", "left": 1.0, "right": 1.0})
    rover.handle({"type": "arm_pose", "base": 90})

    assert rover.wheels == (0.0, 0.0)
    run(rover, 0.5)
    assert rover.pose["base"] != pytest.approx(90.0, abs=1.0)


def test_abort_stops_the_wheels_and_the_plan():
    rover = SimRover([Block(1, 1, 150, 0, 1)])
    start_plan(rover, [PICK, DROP])
    run(rover, 1.0)

    out = rover.handle({"type": "abort"})

    assert codes(out) == ["aborted"]
    pose = dict(rover.pose)
    sent = run(rover, 5)
    assert step_results(sent) == []
    assert rover.pose == pytest.approx(pose, abs=1.0)


# --- link loss ------------------------------------------------------------------------


def test_silence_for_two_seconds_loses_the_link_and_stops_the_wheels():
    rover = SimRover()
    rover.handle({"type": "drive", "left": 1.0, "right": 1.0})

    sent = run(rover, LINK_TIMEOUT_S + 0.5, ping=False)

    assert codes(sent) == ["link_lost"]
    assert rover.wheels == (0.0, 0.0)


def test_a_ping_after_a_lost_link_restores_it():
    rover = SimRover()
    run(rover, LINK_TIMEOUT_S + 0.5, ping=False)

    out = rover.handle({"type": "ping", "t": rover.t})

    assert codes(out) == ["link_restored"]
    assert rover.handle({"type": "ping", "t": rover.t}) == []


def test_a_running_plan_carries_on_through_a_lost_link_and_reports_when_it_returns():
    rover = SimRover([Block(1, 1, 150, 0, 1)])
    start_plan(rover, [PICK, DROP])

    sent = run(rover, 20, ping=False)

    assert codes(sent) == ["link_lost"]  # no plan_finished while nobody is listening
    assert step_results(sent) == [(1, True, ""), (2, True, "")]

    back = rover.handle({"type": "ping", "t": rover.t})

    assert codes(back) == ["link_restored", "plan_finished"]


# --- what the rover reports -----------------------------------------------------------


def test_state_goes_out_at_5_hz_and_sensors_at_2_hz():
    rover = SimRover()

    sent = run(rover, 4.0)

    states = [m for m in sent if m["type"] == "state"]
    sensors = [m for m in sent if m["type"] == "sensors"]
    assert len(states) == pytest.approx(20, abs=2)
    assert len(sensors) == pytest.approx(8, abs=2)


def test_the_state_message_shape_matches_the_protocol():
    state = SimRover().state_message()

    assert set(state) == {"type", "t", "mode", "arm", "plan_id", "step_id", "status"}
    assert set(state["arm"]) == {"base", "shoulder", "elbow", "gripper"}


def test_a_block_ahead_of_the_rover_trips_the_matching_ir_sensor():
    on_left = SimRover([Block(1, 1, 100, 50, 1)])
    on_right = SimRover([Block(1, 1, 100, -50, 1)])
    behind = SimRover([Block(1, 1, -100, 0, 1)])

    assert on_left.sensors_message()["ir_obstacle"] == {"left": True, "right": False}
    assert on_right.sensors_message()["ir_obstacle"] == {"left": False, "right": True}
    assert behind.sensors_message()["ir_obstacle"] == {"left": False, "right": False}


def test_a_block_that_is_being_carried_does_not_trip_the_ir_sensor():
    rover = SimRover([Block(1, 1, 100, 50, 1)])
    rover.carrying = 1

    assert rover.sensors_message()["ir_obstacle"] == {"left": False, "right": False}


def test_a_heat_zone_next_to_the_rover_trips_the_flame_sensor_on_that_side():
    rover = SimRover(heat_zones=[HeatZone(0.0, 40.0, 20.0)])

    assert rover.sensors_message()["ir_flame"] == {"left": True, "right": False}


def test_the_battery_drains_slowly_and_never_below_the_floor():
    rover = SimRover()
    start = rover.battery_v

    run(rover, 10)

    assert start - 0.01 < rover.battery_v < start
    rover.battery_v = 6.0
    run(rover, 5)
    assert rover.battery_v == 6.0


def test_the_snapshot_describes_the_world_for_the_viewer():
    rover = SimRover(
        [Block(1, 1, 150, 0, 1, weight_class="heavy")],
        [HeatZone(10, 20, 30)],
        survivor=(400.0, 0.0),
    )

    snap = rover.snapshot()

    assert snap["rover"] == {"x": 0.0, "y": 0.0, "heading": 0.0}
    assert snap["blocks"][0]["heavy"] is True
    assert snap["blocks"][0]["carried"] is False
    assert snap["heat"] == [{"x": 10, "y": 20, "r": 30}]
    assert snap["survivor"] == (400.0, 0.0)
    assert snap["link_up"] is True


def test_plan_running_is_true_from_the_start_of_a_plan_until_it_finishes():
    rover = SimRover([Block(1, 1, 150, 0, 1)])
    assert rover.plan_running is False

    start_plan(rover, [PICK, DROP])
    assert rover.plan_running is True

    run(rover, 20)
    assert rover.plan_running is False


def test_plan_running_is_false_again_after_an_abort():
    rover = SimRover([Block(1, 1, 150, 0, 1)])
    start_plan(rover, [PICK, DROP])

    rover.handle({"type": "abort"})

    assert rover.plan_running is False
