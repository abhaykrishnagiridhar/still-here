"""The operator under bad conditions: a dead link, a malformed rover message, a restarted laptop."""

from operator_core import Operator
from test_operator import Clock, WALL, key_of, seen


class FlakyLink:
    """Like RealLink: send() returns False, and delivers nothing, while the rover is not connected."""

    def __init__(self, connected=True):
        self.connected = connected
        self.sent = []

    def send(self, message):
        if not self.connected:
            return False
        self.sent.append(message)
        return True


def running_operator(link):
    clock = Clock()
    operator = Operator(link, clock=clock)
    operator.observe(seen(WALL))
    operator.approve(key_of(operator))
    plan_id = link.sent[0]["plan_id"]
    operator.on_rover([{"type": "state", "plan_id": plan_id}])
    assert operator.state()["phase"] == "running"
    return operator, plan_id


def abort_count(link):
    return sum(1 for m in link.sent if m["type"] == "abort")


def test_an_abort_that_could_not_be_delivered_is_sent_again_when_the_link_returns():
    link = FlakyLink()
    operator, _ = running_operator(link)
    link.connected = False

    operator.abort()
    operator.tick()

    assert operator.state()["phase"] == "aborted"
    assert "not heard" in operator.state()["message"]
    assert abort_count(link) == 0

    link.connected = True
    operator.tick()
    operator.tick()

    assert abort_count(link) == 1  # sent once it could be, and not again after that


def test_an_abort_that_was_delivered_is_not_repeated():
    link = FlakyLink()
    operator, _ = running_operator(link)

    operator.abort()
    operator.tick()
    operator.tick()

    assert abort_count(link) == 1
    assert "not heard" not in operator.state()["message"]


def test_approving_a_new_plan_cancels_an_abort_that_never_got_through():
    link = FlakyLink()
    operator, _ = running_operator(link)
    link.connected = False
    operator.abort()
    link.connected = True
    operator.reset()
    operator.observe(seen(WALL))

    operator.approve(key_of(operator))
    operator.tick()

    assert abort_count(link) == 0  # the old abort must not kill the plan that was just approved


def test_a_step_report_with_missing_fields_is_ignored_instead_of_crashing():
    link = FlakyLink()
    operator, plan_id = running_operator(link)

    operator.on_rover([
        {"type": "step_done", "plan_id": plan_id},
        {"type": "step_done", "plan_id": plan_id, "step_id": "one", "ok": True},
        {"type": "step_done", "plan_id": plan_id, "step_id": True, "ok": True},
        {"type": "sensors", "ir_obstacle": "tripped"},
    ])

    assert operator.state()["progress"]["done"] == 0


def test_a_step_report_without_a_reason_still_counts():
    link = FlakyLink()
    operator, plan_id = running_operator(link)

    operator.on_rover([{"type": "step_done", "plan_id": plan_id, "step_id": 1, "ok": True}])

    assert operator.state()["progress"]["done"] == 1


def test_plan_ids_follow_the_calendar_clock_not_the_time_since_boot():
    first = Operator(FlakyLink(), clock=Clock(), wall_clock=lambda: 1_000_000.0)
    later = Operator(FlakyLink(), clock=Clock(), wall_clock=lambda: 1_000_500.0)

    for operator in (first, later):
        operator.observe(seen(WALL))
        operator.approve(key_of(operator))

    assert first._plan_id != later._plan_id


def test_a_bump_during_a_run_is_remembered_in_the_facts_and_the_report():
    link = FlakyLink()
    operator, plan_id = running_operator(link)

    operator.on_rover([{"type": "event", "code": "bump", "detail": "block_5"}])

    assert operator.facts()["bumped"] is True
    assert "brushed block_5" in operator.report_text()


def test_a_bump_without_a_detail_still_counts():
    link = FlakyLink()
    operator, _ = running_operator(link)

    operator.on_rover([{"type": "event", "code": "bump"}])

    assert operator.facts()["bumped"] is True


def test_a_bump_when_no_plan_is_running_is_ignored():
    operator = Operator(FlakyLink(), clock=Clock())
    operator.observe(seen(WALL))

    operator.on_rover([{"type": "event", "code": "bump", "detail": "block_5"}])

    assert operator.facts() is None
