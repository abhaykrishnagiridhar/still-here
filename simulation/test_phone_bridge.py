"""Contract tests for the browser-to-Blender gyro bridge."""

import phone_bridge


def test_a_drive_sample_becomes_a_normalised_wheel_command():
    bridge = phone_bridge.PhoneBridge()

    packet = bridge.handle({"beta": -30, "gamma": 0, "mode": "drive"}, now=1.0)

    assert packet["kind"] == "command"
    assert packet["message"] == {"type": "drive", "left": 1.0, "right": 1.0}


def test_an_arm_sample_contains_the_protocol_arm_pose():
    bridge = phone_bridge.PhoneBridge()
    bridge.handle({"beta": 0, "gamma": 0, "mode": "drive"}, now=1.0)

    packet = bridge.handle(
        {"beta": 0, "gamma": 0, "mode": "arm", "elbow": -80, "grip": False}, now=1.1
    )

    assert packet["message"]["type"] == "arm_pose"
    assert packet["message"]["elbow"] == -80.0
    assert packet["message"]["gripper"] == 0.0


def test_bad_phone_payload_is_rejected_without_emitting_a_command():
    bridge = phone_bridge.PhoneBridge()

    assert bridge.handle({"beta": "not-a-number"}, now=1.0) is None
