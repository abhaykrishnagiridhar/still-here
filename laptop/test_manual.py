"""Manual control: drive and arm commands from the control page, with a dead-man's stop."""


from manual_core import WATCHDOG_S, Manual


class FakeLink:
    def __init__(self):
        self.sent = []

    def send(self, message):
        self.sent.append(message)


class Clock:
    def __init__(self):
        self.now = 50.0

    def __call__(self):
        return self.now


def make(busy=False):
    link, clock = FakeLink(), Clock()
    state = {"busy": busy}
    manual = Manual(link, is_busy=lambda: state["busy"], clock=clock)
    return manual, link, clock, state


def test_a_drive_command_is_sent_to_the_rover():
    manual, link, _, _ = make()

    outcome = manual.drive(0.5, 0.5)

    assert outcome.ok
    assert link.sent == [{"type": "drive", "left": 0.5, "right": 0.5}]


def test_speeds_beyond_full_are_held_at_full():
    manual, link, _, _ = make()

    manual.drive(5, -5)

    assert link.sent == [{"type": "drive", "left": 1.0, "right": -1.0}]


def test_a_speed_that_is_not_a_number_is_refused_and_nothing_is_sent():
    manual, link, _, _ = make()

    outcome = manual.drive("fast", 0)

    assert not outcome.ok and "left" in outcome.message
    assert link.sent == []


def test_an_arm_pose_is_sent_inside_the_joint_limits():
    manual, link, _, _ = make()

    outcome = manual.arm_pose(500, 60, -90, 0, speed=0.5)

    assert outcome.ok
    assert link.sent == [
        {"type": "arm_pose", "base": 90.0, "shoulder": 60.0, "elbow": -90.0, "gripper": 0.0, "speed": 0.5}
    ]


def test_a_bad_arm_pose_is_refused():
    manual, link, _, _ = make()

    assert not manual.arm_pose(0, 60, "bent", 0).ok
    assert link.sent == []


def test_nothing_is_sent_while_a_plan_is_running():
    manual, link, _, _ = make(busy=True)

    assert not manual.drive(1, 1).ok
    assert not manual.arm_pose(0, 60, -90, 90).ok
    assert link.sent == []
    assert "plan is running" in manual.drive(1, 1).message.lower()


def test_the_wheels_are_stopped_when_the_commands_stop_coming():
    manual, link, clock, _ = make()
    manual.drive(1, 1)

    clock.now += WATCHDOG_S + 0.1
    manual.tick()

    assert link.sent[-1] == {"type": "drive", "left": 0.0, "right": 0.0}


def test_a_held_button_that_keeps_sending_is_not_stopped():
    manual, link, clock, _ = make()
    for _ in range(5):
        manual.drive(1, 1)
        clock.now += 0.1
        manual.tick()

    assert all(m["left"] == 1.0 for m in link.sent)


def test_the_stop_is_sent_only_once_after_the_commands_stop():
    manual, link, clock, _ = make()
    manual.drive(1, 1)
    clock.now += 2
    manual.tick()
    manual.tick()

    assert [m for m in link.sent if m["left"] == 0.0] == [{"type": "drive", "left": 0.0, "right": 0.0}]


def test_nothing_is_sent_by_the_watchdog_when_the_wheels_were_never_started():
    manual, link, clock, _ = make()

    clock.now += 10
    manual.tick()

    assert link.sent == []


def test_driving_at_zero_counts_as_stopped_so_there_is_no_extra_stop():
    manual, link, clock, _ = make()
    manual.drive(0, 0)

    clock.now += 10
    manual.tick()

    assert link.sent == [{"type": "drive", "left": 0.0, "right": 0.0}]


def test_stop_halts_the_wheels():
    manual, link, _, _ = make()
    manual.drive(1, 1)

    outcome = manual.stop()

    assert outcome.ok
    assert link.sent[-1] == {"type": "drive", "left": 0.0, "right": 0.0}


def test_stop_during_a_plan_asks_the_rover_to_abort():
    manual, link, _, _ = make(busy=True)

    manual.stop()

    assert {"type": "abort"} in link.sent


def test_the_watchdog_is_well_under_the_rovers_two_second_link_timeout():
    assert WATCHDOG_S < 1.0
