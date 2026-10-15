"""Did the claw really pick the block up? The camera still seeing it where it was says no."""

import pytest

from grip_watch import GripWatch
from models import Block

START = Block(3, 3, 150.0, 40.0, 1)
OTHER = Block(4, 4, 150.0, -40.0, 1)


def watch(**kwargs):
    return GripWatch([START, OTHER], **kwargs)


def test_nothing_is_reported_before_a_pick_is_claimed():
    assert watch().check([START, OTHER], 0.0) is None


def test_a_block_still_in_place_after_the_pick_is_an_empty_grab_once_it_lasts():
    grip = watch(hold_s=1.5)
    grip.picked(3, 10.0)

    assert grip.check([START, OTHER], 10.5) is None  # the arm may still be lifting
    reason = grip.check([START, OTHER], 12.1)

    assert "block_3" in reason and "still" in reason


def test_a_block_that_is_gone_or_has_moved_with_the_claw_is_a_good_grab():
    grip = watch(hold_s=1.5)
    grip.picked(3, 10.0)

    assert grip.check([OTHER], 10.5) is None  # not seen: lifted out of view
    assert grip.check([Block(3, 3, 150.0, 90.0, 1), OTHER], 13.0) is None  # moved away from its place


def test_the_arm_hiding_the_block_for_a_moment_restarts_the_wait():
    grip = watch(hold_s=1.5)
    grip.picked(3, 10.0)
    grip.check([START, OTHER], 10.0)
    grip.check([OTHER], 10.8)  # hidden
    assert grip.check([START, OTHER], 11.0) is None  # the wait started again here
    assert grip.check([START, OTHER], 12.6) is not None


def test_a_block_is_not_watched_after_it_is_put_down():
    grip = watch(hold_s=0.0)
    grip.picked(3, 10.0)
    grip.released(3)

    assert grip.check([START, OTHER], 20.0) is None


def test_other_blocks_are_never_blamed():
    grip = watch(hold_s=0.0)
    grip.picked(3, 10.0)

    assert grip.check([Block(3, 3, 150.0, 90.0, 1), OTHER], 20.0) is None


def test_a_block_the_plan_never_had_is_ignored():
    grip = watch(hold_s=0.0)
    grip.picked(99, 10.0)

    assert grip.check([START, OTHER], 20.0) is None


@pytest.mark.parametrize("kwargs", [{"hold_s": -1.0}, {"tol_mm": 0.0}])
def test_bad_settings_are_refused(kwargs):
    with pytest.raises(ValueError):
        GripWatch([START], **kwargs)
