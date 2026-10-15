"""Does the scene still match what the approved plan assumed?"""

import pytest

from models import Block
from scene_watch import SceneWatch

DROP = (100.0, -90.0)


def block(block_id, x, y):
    return Block(block_id, block_id, float(x), float(y), 1)


BASELINE = [block(1, 150, -80), block(2, 150, 0), block(3, 150, 80)]


def watch(**kwargs):
    return SceneWatch(BASELINE, drop_mm=DROP, **kwargs)


def moved(b, dx=0.0, dy=0.0):
    return block(b.id, b.x + dx, b.y + dy)


def same(*skip):
    return [b for b in BASELINE if b.id not in skip]


def test_a_scene_that_has_not_changed_raises_no_alarm():
    w = watch()

    for t in range(0, 100):
        assert w.check(BASELINE, set(), t * 0.1) is None


def test_measurement_wobble_is_not_a_change():
    w = watch()
    wobbly = [moved(b, 4, -3) for b in BASELINE]

    assert all(w.check(wobbly, set(), t * 0.1) is None for t in range(60))


def test_a_block_that_stays_moved_is_reported_once_it_has_stayed_long_enough():
    w = watch()
    shifted = [moved(BASELINE[1], 40, 0) if b.id == 2 else b for b in BASELINE]

    assert w.check(shifted, set(), 0.0) is None  # just seen: it might be a flicker
    assert w.check(shifted, set(), 0.5) is None
    reason = w.check(shifted, set(), 1.2)

    assert reason is not None and "block_2" in reason and "moved 40 mm" in reason


def test_a_block_that_moves_and_comes_straight_back_is_not_a_change():
    w = watch()
    shifted = [moved(b, 40, 0) if b.id == 2 else b for b in BASELINE]

    assert w.check(shifted, set(), 0.0) is None
    assert w.check(BASELINE, set(), 0.6) is None  # back where it was
    assert w.check(shifted, set(), 0.8) is None  # moved again: the clock starts over
    assert w.check(shifted, set(), 1.5) is None
    assert w.check(shifted, set(), 2.0) is not None


def test_a_block_the_rover_has_started_on_is_allowed_to_move():
    w = watch()
    carried = [moved(b, 80, 60) if b.id == 2 else b for b in BASELINE]

    assert all(w.check(carried, {2}, t * 0.5) is None for t in range(20))


def test_a_block_that_vanishes_is_reported_only_after_a_longer_wait_because_the_arm_can_hide_it():
    w = watch()
    gone = same(2)

    assert w.check(gone, set(), 0.0) is None
    assert w.check(gone, set(), 1.5) is None  # still might be the arm in the way
    reason = w.check(gone, set(), 3.2)

    assert reason is not None and "block_2" in reason and "no longer" in reason


def test_a_block_hidden_for_a_moment_and_then_seen_again_is_fine():
    w = watch()

    assert w.check(same(2), set(), 0.0) is None
    assert w.check(same(2), set(), 2.0) is None
    assert w.check(BASELINE, set(), 2.5) is None
    assert w.check(same(2), set(), 2.6) is None
    assert w.check(same(2), set(), 5.0) is None  # the wait began again at 2.6


def test_a_handled_block_that_vanishes_is_expected():
    w = watch()

    assert all(w.check(same(2), {2}, t) is None for t in range(0, 20))


def test_a_new_block_somewhere_in_the_scene_is_reported():
    w = watch()
    extra = BASELINE + [block(9, 200, 30)]

    assert w.check(extra, set(), 0.0) is None
    reason = w.check(extra, set(), 1.8)

    assert reason is not None and "new block" in reason and "block_9" in reason


def test_a_block_appearing_where_the_rover_drops_blocks_is_expected():
    w = watch()
    dropped = BASELINE + [block(9, 105, -95)]

    assert all(w.check(dropped, set(), t * 0.5) is None for t in range(20))


def test_a_new_block_that_is_one_the_rover_handled_is_expected_anywhere():
    w = watch()
    handled_elsewhere = BASELINE + [block(9, 250, 40)]

    assert all(w.check(handled_elsewhere, {9}, t * 0.5) is None for t in range(20))


def test_the_move_tolerance_can_be_set():
    w = watch(move_tol_mm=50.0)
    shifted = [moved(b, 40, 0) if b.id == 2 else b for b in BASELINE]

    assert all(w.check(shifted, set(), t * 0.5) is None for t in range(10))


def test_the_waits_can_be_set():
    w = watch(moved_hold_s=0.1)
    shifted = [moved(b, 40, 0) if b.id == 2 else b for b in BASELINE]

    w.check(shifted, set(), 0.0)

    assert w.check(shifted, set(), 0.2) is not None


def test_the_most_serious_change_is_reported_first():
    w = watch()
    mixed = [moved(b, 60, 0) if b.id == 1 else b for b in same(3)] + [block(9, 200, 30)]

    w.check(mixed, set(), 0.0)
    reason = w.check(mixed, set(), 3.5)

    assert "block_1" in reason  # moved comes before missing and new


def test_an_empty_baseline_only_watches_for_new_blocks():
    w = SceneWatch([], drop_mm=DROP)

    assert w.check([], set(), 0.0) is None
    w.check([block(5, 200, 0)], set(), 0.0)
    assert w.check([block(5, 200, 0)], set(), 2.0) is not None


@pytest.mark.parametrize("bad", [{"move_tol_mm": 0}, {"moved_hold_s": -1}, {"missing_hold_s": -1}, {"new_hold_s": -1}])
def test_nonsense_settings_are_refused(bad):
    with pytest.raises(ValueError):
        watch(**bad)
