"""Autonomous mode for the simulation: it approves plans by itself, and hands control back to a person.

It never runs the real rover (the server refuses that), and the moment anyone stops a run it switches itself off.
"""

from autopilot import Autopilot
from operator_core import Operator
from test_operator import Clock, WALL, clear_picture, seen


class Link:
    def __init__(self):
        self.sent = []

    def send(self, message):
        self.sent.append(message)


def types(link):
    return [m["type"] for m in link.sent]


def plans(link):
    return [m for m in link.sent if m["type"] == "plan"]


def build(episodes=2, extra=lambda: 0.0, think_s=2.0, pause_s=3.0):
    link, clock = Link(), Clock()
    operator = Operator(link, clock=clock)
    operator.observe(seen(WALL))
    autopilot = Autopilot(
        operator, link, episodes=episodes, extra_clearance=extra, corridor_mm=240.0,
        clock=clock, think_s=think_s, pause_s=pause_s,
    )
    return autopilot, operator, link, clock


def wait(autopilot, clock, seconds, step=0.5):
    for _ in range(round(seconds / step)):
        clock.now += step
        autopilot.tick()


def finish_run(operator, link, events=()):
    plan = next(m for m in reversed(link.sent) if m["type"] == "plan")
    operator.on_rover([{"type": "state", "plan_id": plan["plan_id"]}])
    for step in plan["steps"]:
        operator.on_rover(
            [{"type": "step_done", "plan_id": plan["plan_id"], "step_id": step["id"], "ok": True, "reason": ""}]
        )
    operator.on_rover(list(events))
    operator.on_rover([{"type": "event", "code": "plan_finished", "detail": ""}])
    for _ in range(3):
        operator.observe(clear_picture())


def test_it_waits_a_moment_before_approving_so_the_plan_can_be_seen():
    autopilot, operator, link, clock = build(think_s=2.0)

    wait(autopilot, clock, 1.0)
    assert "plan" not in types(link)

    wait(autopilot, clock, 2.0)
    assert types(link).count("plan") == 1
    assert operator.state()["phase"] == "waiting"


def test_it_approves_only_the_plan_that_stayed_the_same_for_the_whole_wait():
    autopilot, operator, link, clock = build(think_s=2.0)
    wait(autopilot, clock, 1.5)

    operator.observe(seen(WALL[:2] + WALL[3:]))  # the picture changed, so the plan changed
    wait(autopilot, clock, 1.5)

    assert "plan" not in types(link)  # the wait started again
    wait(autopilot, clock, 1.0)
    assert types(link).count("plan") == 1


def test_after_a_finished_run_it_resets_the_course_and_starts_the_next_episode():
    autopilot, operator, link, clock = build(episodes=2, pause_s=3.0)
    wait(autopilot, clock, 3.0)
    finish_run(operator, link)
    assert operator.state()["phase"] == "done"

    wait(autopilot, clock, 4.0)

    assert {"type": "reset_world"} in link.sent
    assert autopilot.summary()["episode"] == 2
    assert operator.state()["phase"] != "done"


def test_it_stops_after_the_last_episode_and_leaves_the_result_on_screen():
    autopilot, operator, link, clock = build(episodes=1, pause_s=3.0)
    wait(autopilot, clock, 3.0)
    finish_run(operator, link)

    wait(autopilot, clock, 5.0)

    summary = autopilot.summary()
    assert summary["active"] is False
    assert "reset_world" not in types(link)
    assert operator.state()["phase"] == "done"
    assert "finished" in summary["message"].lower()


def test_each_episode_is_written_down_with_what_happened():
    autopilot, operator, link, clock = build(episodes=2, pause_s=3.0)
    wait(autopilot, clock, 3.0)
    finish_run(operator, link, events=[{"type": "event", "code": "bump", "detail": "block_5"}])

    wait(autopilot, clock, 1.0)
    first = autopilot.summary()["history"][0]

    assert first["number"] == 1
    assert first["outcome"] == "bumped"
    assert first["brushed"] == "block_5"
    assert first["moved"] == len(plans(link)[0]["steps"]) // 2


def test_a_clean_run_is_called_clean():
    autopilot, operator, link, clock = build()
    wait(autopilot, clock, 3.0)
    finish_run(operator, link)

    wait(autopilot, clock, 1.0)

    assert autopilot.summary()["history"][0]["outcome"] == "clean"


def test_the_corridor_it_used_and_the_one_it_learned_are_both_reported():
    learned = [0.0]
    autopilot, operator, link, clock = build(episodes=2, extra=lambda: learned[0], pause_s=3.0)
    wait(autopilot, clock, 3.0)
    finish_run(operator, link, events=[{"type": "event", "code": "bump", "detail": "block_5"}])
    learned[0] = 10.0  # the server records the run into experience.py while the page shows the result

    wait(autopilot, clock, 1.0)
    first = autopilot.summary()["history"][0]

    assert first["corridor_mm"] == 240.0
    assert first["next_corridor_mm"] == 260.0


def test_a_person_pressing_stop_switches_autonomous_mode_off():
    autopilot, operator, link, clock = build()
    wait(autopilot, clock, 3.0)
    operator.on_rover([{"type": "state", "plan_id": plans(link)[0]["plan_id"]}])

    operator.abort()
    wait(autopilot, clock, 10.0)

    summary = autopilot.summary()
    assert summary["active"] is False
    assert "stopped" in summary["message"].lower()
    assert types(link).count("plan") == 1  # it did not approve another plan


def test_a_stopped_autopilot_never_acts_again():
    autopilot, operator, link, clock = build()
    autopilot.stop("A person took over.")

    wait(autopilot, clock, 10.0)

    assert all(m["type"] == "overlay" for m in link.sent)


def test_it_tells_the_twin_what_episode_it_is_on_and_how_wide_the_corridor_is():
    autopilot, operator, link, clock = build(episodes=3, extra=lambda: 10.0)

    wait(autopilot, clock, 1.0)

    overlay = next(m for m in link.sent if m["type"] == "overlay")
    assert overlay["episode"] == 1 and overlay["episodes"] == 3
    assert overlay["corridor_mm"] == 260.0
    assert overlay["extra_mm"] == 10.0
    assert isinstance(overlay["text"], str) and overlay["text"]


def test_an_unchanged_overlay_is_not_sent_every_tick():
    autopilot, operator, link, clock = build()

    wait(autopilot, clock, 1.0, step=0.1)

    assert types(link).count("overlay") <= 2


def test_the_overlay_names_the_block_that_was_brushed():
    autopilot, operator, link, clock = build()
    wait(autopilot, clock, 3.0)
    finish_run(operator, link, events=[{"type": "event", "code": "bump", "detail": "block_5"}])

    wait(autopilot, clock, 1.0)

    overlays = [m for m in link.sent if m["type"] == "overlay"]
    assert overlays[-1]["brushed"] == "block_5"


def test_when_there_is_no_way_through_it_waits_and_says_so():
    link, clock = Link(), Clock()
    operator = Operator(link, clock=clock)
    autopilot = Autopilot(operator, link, episodes=2, extra_clearance=lambda: 0.0, corridor_mm=240.0, clock=clock)

    wait(autopilot, clock, 5.0)

    assert "plan" not in types(link)
    assert autopilot.summary()["active"] is True
