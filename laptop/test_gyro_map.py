"""Phone tilt to rover messages."""

import pytest

import gyro_map
from gyro_map import GyroSession, arm_command, axis, clamp, drive_command

STOP = {"type": "drive", "left": 0.0, "right": 0.0}


def settle(session, sample, start=1.0, count=60):
    """Hold the same tilt long enough for the smoothing to catch up; return the last messages."""
    out = []
    for i in range(count):
        out = session.update(sample, start + i * 0.05)
    return out


# --- single tilt to number ------------------------------------------------------------


def test_clamp_keeps_a_value_inside_its_range():
    assert clamp(9, -1, 1) == 1
    assert clamp(-9, -1, 1) == -1
    assert clamp(0.3, -1, 1) == 0.3


def test_a_small_wobble_inside_the_dead_zone_gives_zero():
    assert axis(0.0) == 0.0
    assert axis(gyro_map.DEADZONE_DEG) == 0.0
    assert axis(-gyro_map.DEADZONE_DEG) == 0.0


def test_a_full_tilt_gives_full_output_in_either_direction():
    assert axis(gyro_map.TILT_FULL_DEG) == 1.0
    assert axis(-gyro_map.TILT_FULL_DEG) == -1.0
    assert axis(90.0) == 1.0


def test_halfway_between_the_dead_zone_and_full_tilt_gives_half_output():
    halfway = (gyro_map.DEADZONE_DEG + gyro_map.TILT_FULL_DEG) / 2

    assert axis(halfway) == pytest.approx(0.5)


# --- driving --------------------------------------------------------------------------


def test_tilting_the_top_edge_down_drives_forward():
    assert drive_command(-30.0, 0.0) == (1.0, 1.0)


def test_tilting_the_top_edge_up_drives_backward():
    assert drive_command(30.0, 0.0) == (-1.0, -1.0)


def test_tilting_the_right_edge_down_turns_right_on_the_spot():
    assert drive_command(0.0, 30.0) == (1.0, -1.0)


def test_forward_plus_steer_never_asks_for_more_than_full_speed():
    left, right = drive_command(-30.0, 30.0)

    assert max(abs(left), abs(right)) == 1.0
    assert left > right


def test_no_tilt_means_no_drive():
    assert drive_command(0.0, 0.0) == (0.0, 0.0)


# --- arm ------------------------------------------------------------------------------


def test_a_level_phone_holds_the_arm_at_the_centre_pose():
    pose = arm_command(0.0, 0.0, -90.0, True)

    assert pose == {"base": 0.0, "shoulder": 60.0, "elbow": -90.0, "gripper": 90.0}


def test_tilting_swings_the_base_and_moves_the_shoulder():
    pose = arm_command(30.0, 30.0, -90.0, True)

    assert pose["base"] == -90.0  # right edge down swings the arm right
    assert pose["shoulder"] == 120.0


def test_the_elbow_is_limited_and_the_gripper_follows_the_button():
    pose = arm_command(0.0, 0.0, 500.0, False)

    assert pose["elbow"] == gyro_map.ELBOW_LIMIT_DEG
    assert pose["gripper"] == gyro_map.GRIPPER_CLOSED_DEG


# --- one phone ------------------------------------------------------------------------


def test_a_sample_without_numbers_makes_no_message():
    session = GyroSession()

    assert session.update({}, 0.0) == []
    assert session.update({"beta": "up", "gamma": 0}, 0.0) == []
    assert session.update({"beta": None, "gamma": 0}, 0.0) == []


def test_the_first_sample_is_the_centre_so_it_does_not_move_the_rover():
    session = GyroSession()

    out = session.update({"beta": -40.0, "gamma": 25.0}, 0.0)

    assert out == [{"type": "drive", "left": 0.0, "right": 0.0}]


def test_holding_a_forward_tilt_drives_forward_at_full_speed():
    session = GyroSession()
    session.update({"beta": 0.0, "gamma": 0.0}, 0.0)

    out = settle(session, {"beta": -30.0, "gamma": 0.0})

    assert out[-1]["left"] == pytest.approx(1.0, abs=0.01)
    assert out[-1]["right"] == pytest.approx(1.0, abs=0.01)


def test_smoothing_means_one_jump_gives_only_part_of_the_tilt():
    session = GyroSession()
    session.update({"beta": 0.0, "gamma": 0.0}, 0.0)

    out = session.update({"beta": -30.0, "gamma": 0.0}, 0.05)

    assert 0.0 < out[-1]["left"] < 0.5


def test_calibrating_makes_the_current_hold_the_new_centre():
    session = GyroSession()
    session.update({"beta": 0.0, "gamma": 0.0}, 0.0)

    out = settle(session, {"beta": -30.0, "gamma": 0.0, "calibrate": True})

    assert out[-1] == {"type": "drive", "left": 0.0, "right": 0.0}


def test_calibrate_method_sets_the_centre_directly():
    session = GyroSession()
    session.calibrate(-30.0, 0.0)

    out = settle(session, {"beta": -30.0, "gamma": 0.0})

    assert out[-1]["left"] == 0.0


def test_a_stop_sample_stops_the_wheels():
    session = GyroSession()
    session.update({"beta": 0.0, "gamma": 0.0}, 0.0)
    settle(session, {"beta": -30.0, "gamma": 0.0})

    assert session.update({"beta": -30.0, "gamma": 0.0, "stop": True}, 5.0) == [STOP]


def test_switching_to_arm_mode_stops_the_wheels_before_the_first_arm_pose():
    session = GyroSession()
    session.update({"beta": 0.0, "gamma": 0.0, "mode": "drive"}, 0.0)

    out = session.update({"beta": 0.0, "gamma": 0.0, "mode": "arm", "elbow": -80.0, "grip": False}, 0.1)

    assert out[0] == STOP
    assert out[1]["type"] == "arm_pose"
    assert out[1]["elbow"] == -80.0
    assert out[1]["gripper"] == 0.0
    assert out[1]["speed"] == 1.0


def test_an_unknown_mode_keeps_the_current_one():
    session = GyroSession()
    session.update({"beta": 0.0, "gamma": 0.0, "mode": "drive"}, 0.0)

    out = session.update({"beta": 0.0, "gamma": 0.0, "mode": "fly"}, 0.1)

    assert [m["type"] for m in out] == ["drive"]


def test_the_arm_mode_defaults_to_the_home_elbow_and_an_open_gripper():
    session = GyroSession()
    session.update({"beta": 0.0, "gamma": 0.0, "mode": "arm"}, 0.0)

    out = session.update({"beta": 0.0, "gamma": 0.0, "mode": "arm"}, 0.1)

    assert out[-1]["elbow"] == -90.0
    assert out[-1]["gripper"] == gyro_map.GRIPPER_OPEN_DEG


# --- a phone that goes quiet ----------------------------------------------------------


def test_a_phone_that_goes_quiet_stops_the_wheels_once():
    session = GyroSession()
    session.update({"beta": 0.0, "gamma": 0.0}, 0.0)
    settle(session, {"beta": -30.0, "gamma": 0.0}, start=0.1, count=10)  # last sample at 0.55

    assert session.idle(0.6) == []  # not stale yet
    assert session.idle(0.55 + gyro_map.STALE_AFTER_S + 0.1) == [STOP]
    assert session.idle(5.0) == []  # already stopped, say nothing more


def test_a_session_that_never_heard_from_the_phone_stays_silent():
    assert GyroSession().idle(10.0) == []


def test_a_new_sample_after_a_stop_makes_the_phone_live_again():
    session = GyroSession()
    session.update({"beta": 0.0, "gamma": 0.0}, 0.0)
    session.idle(5.0)

    session.update({"beta": -30.0, "gamma": 0.0}, 6.0)

    assert session.idle(6.0 + gyro_map.STALE_AFTER_S + 0.1) == [STOP]
