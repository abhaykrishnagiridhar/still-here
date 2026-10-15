"""The hand-driving console in firmware/rover_control.py."""

import importlib.util
from pathlib import Path

import pytest

from sim_server import SimRoverServer

_SPEC = importlib.util.spec_from_file_location(
    "rover_control", Path(__file__).resolve().parents[1] / "firmware" / "rover_control.py"
)
rover_control = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(rover_control)
Console = rover_control.Console


class FakeLink:
    def __init__(self, connected=True):
        self.connected = connected
        self.sent = []
        self.inbox = []

    def send(self, message):
        if not self.connected:
            return False
        self.sent.append(message)
        return True

    def advance(self, dt):
        out, self.inbox = self.inbox, []
        return out


def make(connected=True, answers=()):
    link, said, pauses = FakeLink(connected), [], []
    queue = list(answers)
    console = Console(link, speed=0.3, say=said.append, ask=lambda prompt: queue.pop(0), sleep=pauses.append)
    return console, link, said, pauses


# --- the wheels -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "direction, expected",
    [("forward", (0.5, 0.5)), ("reverse", (-0.5, -0.5)), ("left", (-0.5, 0.5)), ("right", (0.5, -0.5))],
)
def test_each_direction_maps_to_wheel_speeds_and_a_faster_right_wheel_turns_left(direction, expected):
    assert rover_control.wheels_for(direction, 0.5) == expected


def test_a_speed_beyond_full_is_held_at_full():
    assert rover_control.wheels_for("forward", 5) == (1.0, 1.0)
    assert rover_control.wheels_for("forward", -1) == (0.0, 0.0)


def test_a_drive_button_repeats_its_command_and_then_stops_the_wheels():
    console, link, said, pauses = make()

    console.handle("1")

    drives = [m for m in link.sent if m["type"] == "drive"]
    assert all(m["type"] == "drive" for m in link.sent)
    assert drives[:-1] == [{"type": "drive", "left": 0.3, "right": 0.3}] * (len(drives) - 1)
    assert drives[-1] == {"type": "drive", "left": 0.0, "right": 0.0}
    assert len(drives) == 6  # half a second at one command every 0.1 s, then the stop
    assert pauses and all(p == 0.1 for p in pauses)


def test_the_commands_are_protocol_messages_with_no_old_command_names():
    console, link, _, _ = make()

    for choice in ("1", "2", "3", "4", "5", "6", "7", "8", "s"):
        console.handle(choice)

    assert {m["type"] for m in link.sent} <= {"drive", "arm_pose"}
    assert not any("direction" in m or m["type"] in ("hello", "heartbeat", "pick", "drop", "status") for m in link.sent)


def test_nothing_is_sent_and_the_person_is_told_when_the_rover_is_not_connected():
    console, link, said, _ = make(connected=False)

    console.handle("1")

    assert link.sent == []
    assert said == ["The rover is not connected, so nothing was sent."]  # told once, not six times


def test_stop_sends_zero_speed():
    console, link, _, _ = make()

    console.handle("5")

    assert link.sent == [{"type": "drive", "left": 0.0, "right": 0.0}]


# --- the arm ------------------------------------------------------------------------------------


def test_arm_home_sends_the_home_pose():
    console, link, _, _ = make()

    console.handle("6")

    assert link.sent == [{"type": "arm_pose", "base": 0.0, "shoulder": 60.0, "elbow": -90.0, "gripper": 90.0, "speed": 0.6}]


def test_the_gripper_buttons_change_only_the_gripper():
    console, link, _, _ = make()
    console.move_arm(base=30.0, shoulder=50.0, elbow=-40.0)

    console.handle("8")
    console.handle("7")

    closed, opened = link.sent[-2], link.sent[-1]
    assert (closed["base"], closed["shoulder"], closed["elbow"], closed["gripper"]) == (30.0, 50.0, -40.0, 0.0)
    assert (opened["base"], opened["shoulder"], opened["elbow"], opened["gripper"]) == (30.0, 50.0, -40.0, 90.0)


def test_a_typed_pose_is_sent_and_held_inside_the_joint_limits():
    console, link, _, _ = make(answers=["500 60 -90 0"])

    console.handle("9")

    assert link.sent[0]["base"] == 90.0 and link.sent[0]["gripper"] == 0.0


@pytest.mark.parametrize("answer, message", [("a b c d", "not numbers"), ("1 2 3", "exactly four")])
def test_a_bad_typed_pose_is_explained_and_nothing_is_sent(answer, message):
    console, link, said, _ = make(answers=[answer])

    console.handle("9")

    assert link.sent == [] and message in said[0]


def test_an_arm_move_that_could_not_be_sent_is_not_remembered():
    console, link, said, _ = make(connected=False)
    console.move_arm(base=45.0)

    link.connected = True
    console.handle("8")

    assert link.sent[0]["base"] == 0.0  # the failed move left the pose where it was


# --- listening ------------------------------------------------------------------------------------


def test_status_says_so_when_the_rover_has_not_reported():
    console, _, said, _ = make()

    console.handle("s")

    assert said == ["No state from the rover yet."]


def test_status_shows_the_latest_state_and_sensors():
    console, link, said, _ = make()
    link.inbox = [{"type": "state", "plan_id": None, "status": "idle"}, {"type": "sensors", "battery_v": 8.1}]

    console.handle("s")

    assert any("idle" in line for line in said) and any("battery_v" in line for line in said)


def test_events_and_failed_steps_are_shown_as_they_arrive():
    console, link, said, _ = make()
    link.inbox = [
        {"type": "event", "code": "link_lost", "detail": ""},
        {"type": "step_done", "step_id": 3, "ok": False, "reason": "unreachable"},
        {"type": "step_done", "step_id": 4, "ok": True, "reason": ""},
    ]

    console.handle("")

    assert any("link_lost" in line for line in said)
    assert any("step 3 failed: unreachable" in line for line in said)
    assert not any("step 4" in line for line in said)


# --- the menu ---------------------------------------------------------------------------------------


def test_exit_stops_the_wheels_and_leaves():
    console, link, _, _ = make()

    assert console.handle("0") is False
    assert link.sent[-1] == {"type": "drive", "left": 0.0, "right": 0.0}


def test_a_blank_line_changes_nothing_and_an_unknown_one_is_called_unknown():
    console, link, said, _ = make()

    assert console.handle("") is True
    assert console.handle("zzz") is True

    assert link.sent == [] and said == ["Unknown choice."]


# --- the real thing, against the software rover over a WebSocket -----------------------------------


def test_driving_forward_from_the_console_really_moves_the_rover_and_exit_stops_it(monkeypatch):
    rover = SimRoverServer().start()
    answers = iter(["1", "s", "0"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    try:
        code = rover_control.main(["--rover", f"127.0.0.1:{rover.port}", "--speed", "0.5"])

        assert code == 0
        assert rover.rover.x > 20  # half a second at half speed is about 50 mm
        assert rover.rover.wheels == (0.0, 0.0)
    finally:
        rover.close()


def test_a_rover_that_cannot_be_reached_is_reported_and_exits_with_an_error(monkeypatch, capsys):
    monkeypatch.setattr(rover_control, "CONNECT_WAIT_S", 0.6)

    code = rover_control.main(["--rover", "127.0.0.1:1"])

    assert code == 1
    assert "Could not reach the rover" in capsys.readouterr().err


@pytest.mark.parametrize("args", [["--speed", "0"], ["--speed", "2"], ["--rover", "host:abc"]])
def test_bad_arguments_are_refused(args, capsys):
    assert rover_control.main(args) == 1
    assert capsys.readouterr().err
