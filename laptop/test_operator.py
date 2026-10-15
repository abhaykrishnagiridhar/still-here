"""The operator: what is shown, what the person may approve, and what is sent to the rover."""

from types import SimpleNamespace

import pytest

from models import Block
from operator_core import DROP_POINT_MM, Operator
from planner import plan
from route import route


class FakeLink:
    def __init__(self):
        self.sent = []

    def send(self, message):
        self.sent.append(message)


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


def seen(blocks, survivor_mm=(300.0, 0.0), survivor_px=(320, 100)):
    """What the camera pipeline would hand over for one picture."""
    if survivor_mm is None:
        result = plan(blocks)
    else:
        result = route(blocks, [], (0.0, 0.0), survivor_mm, bounds=BOUNDS)
    return SimpleNamespace(result=result, survivor=survivor_px, px_per_mm=2.0)


BOUNDS = (-10.0, -100.0, 320.0, 100.0)  # the table: the path cannot go round the ends of the wall
WALL = [Block(i, i, 150.0, float(y), 1) for i, y in enumerate((-80, -40, 0, 40, 80), start=1)]


def make(blocks=WALL, **kwargs):
    link, clock = FakeLink(), Clock()
    operator = Operator(link, clock=clock, **kwargs)
    operator.observe(seen(blocks))
    return operator, link, clock


def key_of(operator):
    return operator.state()["plan"]["key"]


def sent_types(link):
    return [m["type"] for m in link.sent]


# --- what is shown --------------------------------------------------------------------


def test_before_anything_is_seen_the_operator_is_scanning():
    state = Operator(FakeLink()).state()

    assert state["phase"] == "scanning"
    assert state["plan"] is None
    assert state["can_approve"] is False


def test_a_route_to_the_survivor_is_ready_to_approve():
    operator, _, _ = make()

    state = operator.state()

    assert state["phase"] == "plan_ready"
    assert state["can_approve"] is True
    assert state["plan"]["ok"] is True
    assert len(state["plan"]["order"]) >= 1


def test_with_no_survivor_found_the_operator_asks_for_a_tap_and_cannot_approve():
    operator, _, _ = make()
    operator.observe(seen(WALL, survivor_mm=None, survivor_px=None))

    state = operator.state()

    assert state["can_approve"] is False
    assert "survivor" in state["message"].lower()


def test_a_route_that_does_not_exist_cannot_be_approved():
    heavy_wall = [
        Block(i, i, 150.0, float(y), 1, weight_class="heavy") for i, y in enumerate((-80, -40, 0, 40, 80), 1)
    ]
    operator, _, _ = make(heavy_wall)

    state = operator.state()

    assert state["plan"]["ok"] is False
    assert state["can_approve"] is False


def test_a_path_that_is_already_clear_has_nothing_to_approve():
    operator, _, _ = make(blocks=[])

    state = operator.state()

    assert state["can_approve"] is False
    assert "clear" in state["message"].lower()


def test_a_tapped_survivor_is_remembered_until_cleared():
    operator = Operator(FakeLink())

    operator.tap_survivor(321.7, 98.2)
    assert operator.survivor_hint == (322, 98)

    operator.clear_survivor()
    assert operator.survivor_hint is None


# --- approving ------------------------------------------------------------------------


def test_approving_sends_the_plan_but_does_not_start_it_until_the_rover_confirms():
    operator, link, _ = make()

    outcome = operator.approve(key_of(operator))

    assert outcome.ok
    assert sent_types(link) == ["plan"]
    assert operator.state()["phase"] == "waiting"


def test_the_plan_sent_picks_each_block_where_it_is_and_drops_it_at_the_drop_point():
    operator, link, _ = make()
    order = operator.state()["plan"]["order"]

    operator.approve(key_of(operator))

    steps = link.sent[0]["steps"]
    assert len(steps) == 2 * len(order)
    assert [s["action"] for s in steps] == ["pick", "drop"] * len(order)
    assert steps[0]["x"] == pytest.approx(order[0]["x"])
    assert steps[0]["y"] == pytest.approx(order[0]["y"])
    assert steps[0]["z"] == 20.0
    assert (steps[1]["x"], steps[1]["y"]) == DROP_POINT_MM
    assert [s["id"] for s in steps] == list(range(1, len(steps) + 1))


def test_when_the_rover_state_shows_the_plan_id_the_plan_is_started():
    operator, link, _ = make()
    operator.approve(key_of(operator))
    plan_id = link.sent[0]["plan_id"]

    operator.on_rover([{"type": "state", "plan_id": plan_id, "status": "idle"}])

    assert sent_types(link) == ["plan", "plan_start"]
    assert link.sent[1]["plan_id"] == plan_id
    assert operator.state()["phase"] == "running"


def test_a_state_for_some_other_plan_does_not_start_anything():
    operator, link, _ = make()
    operator.approve(key_of(operator))

    operator.on_rover([{"type": "state", "plan_id": 999, "status": "idle"}])

    assert sent_types(link) == ["plan"]


def test_a_rover_that_never_confirms_is_given_up_on():
    operator, link, clock = make()
    operator.approve(key_of(operator))

    clock.now += 10
    operator.tick()

    assert operator.state()["phase"] == "aborted"
    assert "confirm" in operator.state()["message"].lower()
    assert "abort" in sent_types(link)


def test_a_plan_that_changed_since_it_was_shown_is_refused():
    operator, link, _ = make()
    shown = key_of(operator)
    changed = [WALL[0], WALL[1], Block(3, 3, 150.0, 0.0, 1, weight_class="heavy"), *WALL[3:]]
    operator.observe(seen(changed))  # the picture changed: a different block is now the one to remove

    outcome = operator.approve(shown)

    assert not outcome.ok
    assert "changed" in outcome.message.lower()
    assert link.sent == []


def test_approving_with_nothing_to_approve_is_refused():
    operator = Operator(FakeLink())

    assert not operator.approve("anything").ok


def test_the_same_plan_cannot_be_approved_twice():
    operator, link, _ = make()
    key = key_of(operator)
    operator.approve(key)

    assert not operator.approve(key).ok
    assert sent_types(link) == ["plan"]


def test_new_pictures_do_not_change_the_plan_once_it_is_approved():
    operator, _, _ = make()
    operator.approve(key_of(operator))
    approved = operator.state()["plan"]["key"]

    changed = [WALL[0], WALL[1], Block(3, 3, 150.0, 0.0, 1, weight_class="heavy"), *WALL[3:]]
    operator.observe(seen(changed))

    assert operator.state()["plan"]["key"] == approved


# --- running and finishing ------------------------------------------------------------


def run_to_the_end(operator, link, steps_ok=True):
    operator.approve(key_of(operator))
    plan_id = link.sent[0]["plan_id"]
    operator.on_rover([{"type": "state", "plan_id": plan_id}])
    for step in link.sent[0]["steps"]:
        operator.on_rover(
            [{"type": "step_done", "plan_id": plan_id, "step_id": step["id"], "ok": steps_ok,
              "reason": "" if steps_ok else "unreachable"}]
        )
    operator.on_rover([{"type": "event", "code": "plan_finished", "detail": ""}])


def test_progress_counts_the_steps_that_are_done():
    operator, link, _ = make()
    operator.approve(key_of(operator))
    plan_id = link.sent[0]["plan_id"]
    operator.on_rover([{"type": "state", "plan_id": plan_id}])

    operator.on_rover([{"type": "step_done", "plan_id": plan_id, "step_id": 1, "ok": True, "reason": ""}])

    assert operator.state()["progress"] == {"done": 1, "total": len(link.sent[0]["steps"])}


def test_finishing_the_plan_ends_in_done():
    operator, link, _ = make()

    run_to_the_end(operator, link)

    assert operator.state()["phase"] == "done"


def test_abort_tells_the_rover_to_stop_and_ends_the_run():
    operator, link, _ = make()
    operator.approve(key_of(operator))

    operator.abort()

    assert "abort" in sent_types(link)
    assert operator.state()["phase"] == "aborted"


def test_a_rover_that_says_it_aborted_ends_the_run():
    operator, link, _ = make()
    operator.approve(key_of(operator))

    operator.on_rover([{"type": "event", "code": "aborted", "detail": ""}])

    assert operator.state()["phase"] == "aborted"


def test_losing_the_link_is_noted_and_shown():
    operator, link, _ = make()
    operator.approve(key_of(operator))
    operator.on_rover([{"type": "state", "plan_id": link.sent[0]["plan_id"]}])

    operator.on_rover([{"type": "event", "code": "link_lost", "detail": ""}])

    assert "link" in operator.state()["message"].lower()


def test_a_new_run_can_start_after_one_finishes():
    operator, link, _ = make()
    run_to_the_end(operator, link)

    operator.reset()
    operator.observe(seen(WALL))

    assert operator.state()["phase"] == "plan_ready"
    assert operator.state()["can_approve"]


# --- the report -----------------------------------------------------------------------


def test_the_report_lists_what_was_picked_what_was_left_and_how_each_step_went():
    blocks = [*WALL[:3], Block(4, 4, 150.0, 40.0, 1, weight_class="heavy"), WALL[4]]
    operator, link, _ = make(blocks)

    run_to_the_end(operator, link)
    report = operator.report()

    assert report["outcome"] == "done"
    assert report["survivor_mm"] == [300.0, 0.0]
    assert {r["id"] for r in report["picked"]} == {b["id"] for b in operator.state()["plan"]["order"]}
    assert all(r["ok"] for r in report["picked"])
    text = operator.report_text()
    assert "block_" in text and "mm" in text


def test_a_failed_step_shows_up_in_the_report_with_its_reason():
    operator, link, _ = make()

    run_to_the_end(operator, link, steps_ok=False)
    report = operator.report()

    assert any(not r["ok"] and r["reason"] == "unreachable" for r in report["picked"])
    assert "unreachable" in operator.report_text()


def test_a_report_before_any_run_says_nothing_has_run():
    operator = Operator(FakeLink())

    assert operator.report()["outcome"] == "not_run"
    assert "no run" in operator.report_text().lower()
