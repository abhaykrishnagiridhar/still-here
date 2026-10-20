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
        result = route(blocks, [], (0.0, 0.0), survivor_mm, bounds=BOUNDS, corridor=60.0)
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


def clear_picture():
    """The camera sees the way to the survivor open: nothing left to remove."""
    return seen([])


def run_to_the_end(operator, link, steps_ok=True, clear=True):
    operator.approve(key_of(operator))
    plan_id = link.sent[0]["plan_id"]
    operator.on_rover([{"type": "state", "plan_id": plan_id}])
    for step in link.sent[0]["steps"]:
        operator.on_rover(
            [{"type": "step_done", "plan_id": plan_id, "step_id": step["id"], "ok": steps_ok,
              "reason": "" if steps_ok else "unreachable"}]
        )
    operator.on_rover([{"type": "event", "code": "plan_finished", "detail": ""}])
    if clear:
        for _ in range(3):
            operator.observe(clear_picture())


def test_progress_counts_the_steps_that_are_done():
    operator, link, _ = make()
    operator.approve(key_of(operator))
    plan_id = link.sent[0]["plan_id"]
    operator.on_rover([{"type": "state", "plan_id": plan_id}])

    operator.on_rover([{"type": "step_done", "plan_id": plan_id, "step_id": 1, "ok": True, "reason": ""}])

    assert operator.state()["progress"] == {"done": 1, "total": len(link.sent[0]["steps"])}


def test_finishing_the_plan_ends_in_done_once_the_camera_confirms_it():
    operator, link, _ = make()

    run_to_the_end(operator, link)

    state = operator.state()
    assert state["phase"] == "done"
    assert state["verified"] is True
    assert "clear" in state["message"].lower()


def test_when_the_rover_finishes_the_camera_is_asked_to_confirm():
    operator, link, _ = make()

    run_to_the_end(operator, link, clear=False)

    state = operator.state()
    assert state["phase"] == "verifying"
    assert state["verified"] is None


def test_one_clear_picture_is_not_enough_to_confirm():
    operator, link, _ = make()
    run_to_the_end(operator, link, clear=False)

    operator.observe(clear_picture())

    assert operator.state()["phase"] == "verifying"


def test_a_picture_that_still_shows_blocks_in_the_way_does_not_confirm():
    operator, link, _ = make()
    run_to_the_end(operator, link, clear=False)

    for _ in range(5):
        operator.observe(seen(WALL))  # the same wall as before

    assert operator.state()["phase"] == "verifying"


def test_a_run_the_camera_cannot_confirm_ends_unverified_after_the_timeout():
    operator, link, clock = make()
    run_to_the_end(operator, link, clear=False)

    clock.now += 30
    operator.tick()

    state = operator.state()
    assert state["phase"] == "done"
    assert state["verified"] is False
    assert "still sees" in state["message"].lower()


def test_a_picture_with_no_survivor_does_not_confirm():
    operator, link, _ = make()
    run_to_the_end(operator, link, clear=False)

    for _ in range(5):
        operator.observe(seen([], survivor_mm=None, survivor_px=None))

    assert operator.state()["phase"] == "verifying"


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


# --- the facts behind the report --------------------------------------------------------


def test_the_facts_of_a_verified_run():
    operator, link, _ = make()
    run_to_the_end(operator, link)

    facts = operator.facts()

    planned = len(link.sent[0]["steps"])
    assert facts == {
        "run_id": f"stillhere-run-{link.sent[0]['plan_id']}",
        "status": "completed",
        "verified": True,
        "steps_completed": planned,
        "steps_planned": planned,
        "obstacles_detected": 0,
        "safe_stop_triggered": False,
        "disturbed_neighbour": False,
        "bumped": False,
    }


def test_steps_the_rover_reported_as_failed_are_not_counted_as_completed():
    operator, link, clock = make()
    run_to_the_end(operator, link, steps_ok=False, clear=False)
    clock.now += 30
    operator.tick()

    facts = operator.facts()

    assert facts["steps_completed"] == 0
    assert facts["status"] == "unverified"
    assert facts["verified"] is False


def test_an_aborted_run_is_a_safe_stop():
    operator, link, _ = make()
    operator.approve(key_of(operator))

    operator.abort()

    facts = operator.facts()
    assert facts["status"] == "aborted"
    assert facts["safe_stop_triggered"] is True
    assert facts["verified"] is False


def test_each_new_ir_obstacle_trip_is_counted_once():
    operator, link, _ = make()
    operator.approve(key_of(operator))
    trip = {"type": "sensors", "ir_obstacle": {"left": True, "right": False}}
    clear = {"type": "sensors", "ir_obstacle": {"left": False, "right": False}}

    operator.on_rover([trip, trip, clear, trip, clear])

    assert operator.facts()["obstacles_detected"] == 2


def test_the_finished_facts_are_handed_over_once():
    operator, link, _ = make()
    assert operator.take_finished_facts() is None
    run_to_the_end(operator, link)

    first = operator.take_finished_facts()

    assert first["status"] == "completed"
    assert operator.take_finished_facts() is None


def test_an_aborted_run_also_hands_over_its_facts_once():
    operator, link, _ = make()
    operator.approve(key_of(operator))
    operator.abort()

    assert operator.take_finished_facts()["status"] == "aborted"
    assert operator.take_finished_facts() is None


def test_the_text_report_is_facts_first_with_an_allowed_summary_and_the_block_lines():
    operator, link, _ = make()
    run_to_the_end(operator, link)

    lines = operator.report_text().splitlines()

    assert lines[0] == "STILL HERE - SAFE-PATH REPORT"
    assert "Verified: True" in lines
    assert "Summary: Run completed and verified." in lines
    assert any(line.startswith("block_") and "moved out of the way" in line for line in lines)


def test_an_unverified_run_is_reported_as_not_verified():
    operator, link, clock = make()
    run_to_the_end(operator, link, clear=False)
    clock.now += 30
    operator.tick()

    text = operator.report_text()

    assert "Summary: Run was not verified." in text
    assert "completed and verified" not in text



def test_each_block_is_dropped_in_its_own_slot_so_they_never_pile_up():
    from operator_core import DROP_SLOTS_MM

    link = FakeLink()
    operator = Operator(link, clock=Clock())
    wall = [Block(i, i, 150.0, float(y), 1) for i, y in enumerate((-75, -25, 25, 75), start=1)]
    result = route(wall, [], (0.0, 0.0), (300.0, 0.0), bounds=(-10.0, -200.0, 320.0, 200.0), corridor=240.0)
    operator.observe(SimpleNamespace(result=result, survivor=(320, 100), px_per_mm=2.0))
    order = operator.state()["plan"]["order"]
    assert len(order) == 4

    operator.approve(key_of(operator))

    drops = [(s["x"], s["y"]) for s in link.sent[0]["steps"] if s["action"] == "drop"]
    assert drops == [DROP_SLOTS_MM[i % len(DROP_SLOTS_MM)] for i in range(4)]
    assert len(set(drops)) == 4
