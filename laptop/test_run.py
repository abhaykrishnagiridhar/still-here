"""The console run: scan, plan, approve, send, start, verify."""

import pytest

import run
from run import MockRoverLink, RoverLink, build_facts, console_approval, run_controller, summary_for

STEPS = [
    {"id": 1, "action": "pick", "x": 100, "y": 20, "z": 20},
    {"id": 2, "action": "drop", "x": 180, "y": 20, "z": 20},
]


class ScriptedRover(RoverLink):
    """Answers from a script, and remembers everything it was sent."""

    def __init__(self, accepts=(True,), starts=(True,), verdicts=(True,)):
        self.accepts, self.starts, self.verdicts = list(accepts), list(starts), list(verdicts)
        self.sent, self.scans = [], 0

    def scan(self):
        self.scans += 1
        return {"steps": STEPS}

    def send(self, message):
        self.sent.append(message)
        if message["type"] == "plan":
            return {"accepted": self.accepts.pop(0)}
        if message["type"] == "plan_start":
            return {"started": self.starts.pop(0)}
        return {}

    def verify(self, plan):
        ok = self.verdicts.pop(0)
        return {"verified": ok, "steps_completed": len(plan["steps"]) if ok else 0, "obstacles_detected": 0}


def yes(plan):
    return True


def types(rover):
    return [m["type"] for m in rover.sent]


def test_an_approved_plan_is_sent_started_and_verified():
    rover = ScriptedRover()

    result = run_controller(rover, yes)

    assert result.status == "completed"
    assert result.plan_id == 1 and result.attempts == 1
    assert types(rover) == ["plan", "plan_start"]


def test_the_plan_sent_to_the_rover_has_a_whole_number_id():
    rover = ScriptedRover()

    run_controller(rover, yes)

    assert rover.sent[0]["plan_id"] == 1
    assert rover.sent[1]["plan_id"] == 1


def test_a_plan_the_operator_refuses_is_never_sent_and_the_rover_is_told_to_stop():
    rover = ScriptedRover()

    result = run_controller(rover, lambda plan: False)

    assert result.status == "aborted"
    assert types(rover) == ["abort"]


def test_a_rejected_plan_is_tried_again_with_a_fresh_scan():
    rover = ScriptedRover(accepts=(False, True))

    result = run_controller(rover, yes)

    assert result.status == "completed" and result.attempts == 2
    assert rover.scans == 2
    assert [m.get("plan_id") for m in rover.sent if m["type"] == "plan"] == [1, 2]


def test_a_plan_that_will_not_start_is_tried_again():
    rover = ScriptedRover(accepts=(True, True), starts=(False, True), verdicts=(True,))

    result = run_controller(rover, yes)

    assert result.status == "completed" and result.attempts == 2


def test_a_failed_check_is_tried_again_and_then_passes():
    rover = ScriptedRover(accepts=(True, True), starts=(True, True), verdicts=(False, True))

    result = run_controller(rover, yes)

    assert result.status == "completed" and result.attempts == 2


def test_after_too_many_failures_the_run_gives_up_and_stops_the_rover():
    rover = ScriptedRover(accepts=(True,) * 3, starts=(True,) * 3, verdicts=(False,) * 3)

    result = run_controller(rover, yes, max_attempts=3)

    assert result.status == "failed" and result.plan_id is None
    assert types(rover)[-1] == "abort"


def test_a_scan_with_no_steps_is_refused_before_anything_is_sent():
    class EmptyRover(ScriptedRover):
        def scan(self):
            return {"steps": []}

    rover = EmptyRover()

    with pytest.raises(ValueError, match="at least one step"):
        run_controller(rover, yes)
    assert rover.sent == []


def test_the_mock_rover_verifies_only_a_plan_that_was_started():
    rover = MockRoverLink()
    plan = {"type": "plan", "plan_id": 1, "steps": STEPS}
    rover.send(plan)

    assert rover.verify(plan)["verified"] is False

    rover.send({"type": "plan_start", "plan_id": 1})
    verdict = rover.verify(plan)
    assert verdict["verified"] is True and verdict["steps_completed"] == 2


def test_the_mock_rover_ignores_messages_it_does_not_know():
    assert MockRoverLink().send({"type": "mystery"}) == {"accepted": False}


def test_the_base_link_must_be_filled_in():
    link = RoverLink()
    for call in (link.scan, lambda: link.send({}), lambda: link.verify({})):
        with pytest.raises(NotImplementedError):
            call()


@pytest.mark.parametrize(
    "answer, expected",
    [("yes", True), ("Y", True), (" y ", True), ("no", False), ("", False), ("maybe", False)],
)
def test_console_approval_accepts_yes_and_nothing_else(monkeypatch, answer, expected):
    monkeypatch.setattr("builtins.input", lambda prompt="": answer)

    assert console_approval({}) is expected


def test_the_facts_come_from_what_the_rover_reported_not_from_assumptions():
    result = run.RunResult("completed", 2, 1, "ok", {"verified": True, "steps_completed": 1, "obstacles_detected": 3})

    facts = build_facts(result, planned_steps=2, aborted=False)

    assert facts["steps_completed"] == 1  # not assumed equal to the 2 planned
    assert facts["obstacles_detected"] == 3
    assert facts["run_id"] == "stillhere-run-2"
    assert summary_for(facts) is None  # 1 of 2 steps: no allowed summary is supported


def test_a_failed_run_has_an_unknown_id_and_is_not_verified():
    result = run.RunResult("failed", None, 3, "gave up", {"verified": False})

    facts = build_facts(result, planned_steps=2, aborted=True)

    assert facts["run_id"] == "stillhere-run-unknown"
    assert facts["verified"] is False and facts["safe_stop_triggered"] is True
    assert summary_for(facts) == "Run stopped for safety."


def test_a_verified_result_without_the_counts_is_not_called_completed():
    result = run.RunResult("completed", 1, 1, "ok", {"verified": True})

    facts = build_facts(result, planned_steps=2, aborted=False)

    assert facts["steps_completed"] == 0
    assert summary_for(facts) is None
