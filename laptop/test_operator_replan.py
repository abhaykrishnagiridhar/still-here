"""When the scene changes while the rover works: stop, write it up, and offer a fresh plan."""

from types import SimpleNamespace

from models import Block
from operator_core import DROP_POINT_MM, Operator
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


BOUNDS = (-10.0, -100.0, 320.0, 100.0)  # the table: the path cannot go round the ends of the wall
WALL = [Block(i, i, 150.0, float(y), 1) for i, y in enumerate((-80, -40, 0, 40, 80), start=1)]


def seen(blocks):
    """What the camera pipeline would hand over for one picture, scene included."""
    result = route(blocks, [], (0.0, 0.0), (300.0, 0.0), bounds=BOUNDS, corridor=60.0)
    return SimpleNamespace(
        result=result, survivor=(320, 100), px_per_mm=2.0, scene=SimpleNamespace(blocks=tuple(blocks))
    )


def key_of(operator):
    return operator.state()["plan"]["key"]


def running(blocks=WALL):
    link, clock = FakeLink(), Clock()
    operator = Operator(link, clock=clock)
    operator.observe(seen(blocks))
    operator.approve(key_of(operator))
    plan_id = link.sent[0]["plan_id"]
    operator.on_rover([{"type": "state", "plan_id": plan_id}])
    assert operator.state()["phase"] == "running"
    return operator, link, clock, plan_id


def watch_for(operator, clock, blocks, seconds, step=0.25):
    """Show the operator the same picture over a stretch of time."""
    elapsed = 0.0
    while elapsed <= seconds:
        operator.observe(seen(blocks))
        clock.now += step
        elapsed += step


def untouched_block(operator):
    return operator.state()["plan"]["left"][0]["id"]


def with_block(blocks, block_id, dx=0.0, dy=0.0):
    return [Block(b.id, b.marker_id, b.x + dx, b.y + dy, b.layer) if b.id == block_id else b for b in blocks]


# --- stopping and offering a new plan -------------------------------------------------------


def test_a_block_the_rover_has_not_touched_moving_stops_the_rover_and_offers_a_new_plan():
    operator, link, clock, _ = running()
    moved_id = untouched_block(operator)

    watch_for(operator, clock, with_block(WALL, moved_id, dx=40.0), 2.0)

    assert {"type": "abort"} in link.sent
    state = operator.state()
    assert state["phase"] == "plan_ready"
    assert f"block_{moved_id} moved" in state["notice"]
    assert "stopped" in state["notice"].lower()
    assert state["can_approve"] is True


def test_the_fresh_plan_can_be_approved_and_is_a_new_plan_for_the_rover():
    operator, link, clock, old_plan = running()
    watch_for(operator, clock, with_block(WALL, untouched_block(operator), dx=40.0), 2.0)

    outcome = operator.approve(key_of(operator))

    plans = [m for m in link.sent if m["type"] == "plan"]
    assert outcome.ok and len(plans) == 2
    assert plans[1]["plan_id"] != old_plan
    assert operator.state()["notice"] is None  # the person has seen it and approved


def test_a_change_before_the_rover_has_confirmed_the_plan_also_cancels_it():
    link, clock = FakeLink(), Clock()
    operator = Operator(link, clock=clock)
    operator.observe(seen(WALL))
    operator.approve(key_of(operator))
    assert operator.state()["phase"] == "waiting"

    watch_for(operator, clock, with_block(WALL, untouched_block(operator), dx=40.0), 2.0)

    assert operator.state()["phase"] == "plan_ready"
    assert {"type": "abort"} in link.sent


def test_the_stopped_run_is_written_up_as_a_safe_stop_once():
    operator, link, clock, _ = running()
    watch_for(operator, clock, with_block(WALL, untouched_block(operator), dx=40.0), 2.0)

    facts = operator.take_finished_facts()

    assert facts["status"] == "aborted"
    assert facts["safe_stop_triggered"] is True
    assert facts["verified"] is False
    assert operator.take_finished_facts() is None


def test_what_the_rover_says_about_the_old_plan_is_ignored_after_a_stop():
    operator, link, clock, old_plan = running()
    watch_for(operator, clock, with_block(WALL, untouched_block(operator), dx=40.0), 2.0)
    sent_before = len(link.sent)

    operator.on_rover([
        {"type": "state", "plan_id": old_plan, "status": "idle"},
        {"type": "step_done", "plan_id": old_plan, "step_id": 3, "ok": True, "reason": ""},
        {"type": "event", "code": "plan_finished", "detail": ""},
        {"type": "event", "code": "aborted", "detail": ""},
        {"type": "event", "code": "bad_plan", "detail": ""},
    ])

    assert len(link.sent) == sent_before  # nothing was started because of an old confirmation
    assert operator.state()["phase"] == "plan_ready"
    assert operator.state()["progress"]["done"] == 0


def test_starting_a_new_run_clears_the_notice():
    operator, link, clock, _ = running()
    watch_for(operator, clock, with_block(WALL, untouched_block(operator), dx=40.0), 2.0)
    assert operator.state()["notice"]

    operator.reset()

    assert operator.state()["notice"] is None


def test_a_normal_run_has_no_notice():
    link = FakeLink()
    operator = Operator(link, clock=Clock())
    operator.observe(seen(WALL))

    assert operator.state()["notice"] is None


# --- what does not stop the rover ----------------------------------------------------------------


def test_a_small_wobble_does_not_stop_the_rover():
    operator, link, clock, _ = running()

    watch_for(operator, clock, with_block(WALL, untouched_block(operator), dx=5.0), 6.0)

    assert operator.state()["phase"] == "running"
    assert {"type": "abort"} not in link.sent


def test_a_movement_that_does_not_last_does_not_stop_the_rover():
    operator, link, clock, _ = running()
    moved_id = untouched_block(operator)

    watch_for(operator, clock, with_block(WALL, moved_id, dx=40.0), 0.5)
    watch_for(operator, clock, WALL, 2.0)

    assert operator.state()["phase"] == "running"


def test_the_block_the_rover_is_working_on_is_allowed_to_move():
    operator, link, clock, _ = running()
    first = operator.state()["plan"]["order"][0]["id"]

    watch_for(operator, clock, with_block(WALL, first, dx=90.0, dy=60.0), 5.0)

    assert operator.state()["phase"] == "running"


def test_a_block_the_rover_has_already_moved_does_not_count_as_missing():
    operator, link, clock, plan_id = running()
    first = operator.state()["plan"]["order"][0]["id"]
    operator.on_rover([{"type": "step_done", "plan_id": plan_id, "step_id": 1, "ok": True, "reason": ""}])
    operator.on_rover([{"type": "step_done", "plan_id": plan_id, "step_id": 2, "ok": True, "reason": ""}])

    watch_for(operator, clock, [b for b in WALL if b.id != first], 6.0)

    assert operator.state()["phase"] == "running"


def test_a_block_later_in_the_plan_is_not_exempt_until_the_rover_reaches_it():
    two_walls = WALL + [Block(10 + i, 10 + i, 230.0, float(y), 1) for i, y in enumerate((-80, -40, 0, 40, 80))]
    operator, link, clock, _ = running(two_walls)
    order = operator.state()["plan"]["order"]
    assert len(order) == 2  # one block out of each wall

    watch_for(operator, clock, with_block(two_walls, order[1]["id"], dy=40.0), 2.0)

    assert operator.state()["phase"] == "plan_ready"


def test_the_same_movement_of_the_first_block_in_the_plan_is_allowed():
    two_walls = WALL + [Block(10 + i, 10 + i, 230.0, float(y), 1) for i, y in enumerate((-80, -40, 0, 40, 80))]
    operator, link, clock, _ = running(two_walls)
    order = operator.state()["plan"]["order"]

    watch_for(operator, clock, with_block(two_walls, order[0]["id"], dy=40.0), 2.0)

    assert operator.state()["phase"] == "running"


def test_a_block_appearing_where_the_rover_drops_blocks_is_expected():
    operator, link, clock, _ = running()
    drop_x, drop_y = DROP_POINT_MM

    watch_for(operator, clock, [*WALL, Block(9, 9, drop_x + 5, drop_y - 5, 1)], 5.0)

    assert operator.state()["phase"] == "running"


def test_without_scene_information_nothing_is_watched():
    def bare(blocks):
        observation = seen(blocks)
        del observation.scene
        return observation

    link, clock = FakeLink(), Clock()
    operator = Operator(link, clock=clock)
    operator.observe(bare(WALL))
    operator.approve(key_of(operator))
    operator.on_rover([{"type": "state", "plan_id": link.sent[0]["plan_id"]}])

    for _ in range(20):
        operator.observe(bare(with_block(WALL, untouched_block(operator), dx=90.0)))
        clock.now += 0.5

    assert operator.state()["phase"] == "running"


def test_the_scene_is_not_watched_while_the_camera_is_checking_the_result():
    operator, link, clock, _ = running()
    operator.on_rover([{"type": "event", "code": "plan_finished", "detail": ""}])
    assert operator.state()["phase"] == "verifying"

    watch_for(operator, clock, with_block(WALL, untouched_block(operator), dx=90.0), 5.0)

    assert operator.state()["phase"] == "verifying"
    assert {"type": "abort"} not in link.sent


# --- changes that do stop it -------------------------------------------------------------------


def test_a_block_that_vanishes_for_good_stops_the_rover_after_a_longer_wait():
    operator, link, clock, _ = running()
    gone_id = untouched_block(operator)
    without = [b for b in WALL if b.id != gone_id]

    watch_for(operator, clock, without, 1.5)
    assert operator.state()["phase"] == "running"
    watch_for(operator, clock, without, 3.5)

    assert operator.state()["phase"] == "plan_ready"
    assert "no longer seen" in operator.state()["notice"]


def test_a_new_block_appearing_in_the_scene_stops_the_rover():
    operator, link, clock, _ = running()

    watch_for(operator, clock, [*WALL, Block(9, 9, 200.0, 30.0, 1)], 2.5)

    assert operator.state()["phase"] == "plan_ready"
    assert "new block" in operator.state()["notice"]
