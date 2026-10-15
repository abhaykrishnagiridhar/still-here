"""Messages to the rover: checked before they are sent."""

import json

import pytest

from plan_message import (
    build_abort_message,
    build_plan_message,
    build_plan_start_message,
    encode_message,
)

PICK = {"id": 1, "action": "pick", "x": 100, "y": 20, "z": 20}
DROP = {"id": 2, "action": "drop", "x": 100.5, "y": -90, "z": 20}


def test_a_plan_message_has_the_protocol_shape():
    message = build_plan_message(7, [PICK, DROP])

    assert message == {"type": "plan", "plan_id": 7, "steps": [PICK, DROP]}


def test_extra_fields_on_a_step_are_not_passed_on():
    message = build_plan_message(1, [{**PICK, "note": "secret"}])

    assert message["steps"] == [PICK]


@pytest.mark.parametrize("plan_id", [0, -3, True, "run-001", "", None, 2.5])
def test_a_plan_id_must_be_a_positive_whole_number(plan_id):
    with pytest.raises(ValueError, match="plan_id"):
        build_plan_message(plan_id, [PICK])


def test_a_plan_with_no_steps_is_refused():
    with pytest.raises(ValueError, match="at least one step"):
        build_plan_message(1, [])


def test_duplicate_step_ids_are_refused():
    with pytest.raises(ValueError, match="unique"):
        build_plan_message(1, [PICK, {**DROP, "id": 1}])


@pytest.mark.parametrize(
    "step, message",
    [
        ({"id": 1, "action": "pick", "x": 1, "y": 2}, "missing"),
        ({**PICK, "action": "juggle"}, "pick' or 'drop"),
        ({**PICK, "id": 0}, "positive integer"),
        ({**PICK, "id": True}, "positive integer"),
        ({**PICK, "x": "100"}, "x must be a number"),
        ({**PICK, "z": None}, "z must be a number"),
        ({**PICK, "y": True}, "y must be a number"),
    ],
)
def test_a_bad_step_says_what_is_wrong(step, message):
    with pytest.raises(ValueError, match=message):
        build_plan_message(1, [step])


def test_plan_start_and_abort_messages():
    assert build_plan_start_message(7) == {"type": "plan_start", "plan_id": 7}
    assert build_abort_message() == {"type": "abort"}


def test_a_plan_start_with_a_bad_id_is_refused():
    with pytest.raises(ValueError, match="plan_id"):
        build_plan_start_message("one")


def test_a_message_is_sent_as_one_compact_json_object():
    text = encode_message(build_plan_start_message(3))

    assert text == '{"type":"plan_start","plan_id":3}'
    assert json.loads(text)["plan_id"] == 3


@pytest.mark.parametrize("message", [{"plan_id": 1}, {"type": 5}, "plan", None, ["type"]])
def test_a_message_without_a_text_type_is_refused(message):
    with pytest.raises(ValueError, match="type"):
        encode_message(message)


def test_a_number_json_cannot_carry_is_refused():
    with pytest.raises(ValueError):
        encode_message({"type": "drive", "left": float("nan"), "right": 0})


# --- manual control messages ------------------------------------------------------------------

from plan_message import ARM_LIMITS_DEG, build_arm_pose_message, build_drive_message  # noqa: E402


def test_a_drive_message_carries_both_wheel_speeds():
    assert build_drive_message(0.5, -0.25) == {"type": "drive", "left": 0.5, "right": -0.25}


def test_wheel_speeds_beyond_full_are_held_at_full():
    assert build_drive_message(9, -9) == {"type": "drive", "left": 1.0, "right": -1.0}


@pytest.mark.parametrize("bad", ["fast", None, True, float("nan"), float("inf")])
def test_a_wheel_speed_that_is_not_a_number_is_refused(bad):
    with pytest.raises(ValueError, match="left"):
        build_drive_message(bad, 0)


def test_an_arm_pose_message_keeps_every_joint_inside_its_limits():
    message = build_arm_pose_message(500, -50, 400, 200, speed=5)

    assert message == {
        "type": "arm_pose", "base": 90.0, "shoulder": 0.0, "elbow": 135.0, "gripper": 90.0, "speed": 1.0,
    }


def test_an_arm_pose_inside_the_limits_is_passed_as_it_is():
    message = build_arm_pose_message(10, 60, -90, 0, speed=0.5)

    assert (message["base"], message["shoulder"], message["elbow"], message["gripper"], message["speed"]) == (
        10.0, 60.0, -90.0, 0.0, 0.5,
    )


def test_a_very_slow_arm_move_is_held_at_the_slowest_allowed():
    assert build_arm_pose_message(0, 60, -90, 0, speed=0)["speed"] == 0.05


def test_an_arm_joint_that_is_not_a_number_is_refused_by_name():
    with pytest.raises(ValueError, match="elbow"):
        build_arm_pose_message(0, 60, "bent", 0)


def test_the_arm_limits_match_the_software_rover():
    import sim_rover

    assert ARM_LIMITS_DEG == {j: tuple(sim_rover._LIMITS[j]) for j in sim_rover.JOINTS}
