"""Tests for pixels-to-millimetres, learned from the blocks themselves (40 mm cubes)."""

import pytest

from scale import BLOCK_MM, ScaleEstimator, block_size_ok, to_mm, to_px

ORIGIN = (320.0, 480.0)  # bottom centre of a 640 x 480 picture: where the rover is


def test_the_block_is_40_mm_wide():
    assert BLOCK_MM == 40.0


def test_a_60_pixel_block_means_1_point_5_pixels_per_millimetre():
    estimator = ScaleEstimator(min_samples=3)
    result = None
    for _ in range(3):
        result = estimator.update([60.0, 60.0])

    assert result == pytest.approx(1.5)


def test_there_is_no_scale_until_enough_frames_have_been_seen():
    estimator = ScaleEstimator(min_samples=5)

    assert estimator.update([60.0]) is None
    assert estimator.update([60.0]) is None
    assert estimator.px_per_mm is None


def test_frames_with_no_blocks_do_not_count_and_do_not_spoil_the_scale():
    estimator = ScaleEstimator(min_samples=2)
    estimator.update([60.0])
    estimator.update([])
    estimator.update([60.0])

    assert estimator.px_per_mm == pytest.approx(1.5)


def test_one_oversized_blob_does_not_throw_the_scale_off():
    estimator = ScaleEstimator(min_samples=1)

    result = estimator.update([60.0, 60.0, 60.0, 300.0])  # three blocks and a table edge

    assert result == pytest.approx(1.5)


def test_the_scale_follows_the_camera_when_it_moves():
    estimator = ScaleEstimator(window=10, min_samples=3)
    for _ in range(10):
        estimator.update([60.0])
    for _ in range(10):
        estimator.update([30.0])  # the camera moved away, blocks look half as big

    assert estimator.px_per_mm == pytest.approx(0.75)


def test_a_block_sized_blob_is_accepted_and_a_table_or_a_speck_is_not():
    scale = 1.5  # a 40 mm block is 60 pixels wide

    assert block_size_ok(60.0, scale)
    assert block_size_ok(80.0, scale)  # a nearer block looks a little bigger
    assert not block_size_ok(150.0, scale)  # 100 mm: a table edge or a wall
    assert not block_size_ok(15.0, scale)  # 10 mm: a speck


def test_any_blob_is_accepted_while_the_scale_is_still_unknown():
    assert block_size_ok(500.0, None)


def test_the_rover_position_is_the_origin():
    assert to_mm(ORIGIN, ORIGIN, 1.5) == (0.0, 0.0)


def test_a_point_straight_ahead_of_the_rover_is_forward_not_sideways():
    forward, left = to_mm((320.0, 330.0), ORIGIN, 1.5)  # 150 pixels up the picture

    assert forward == pytest.approx(100.0)
    assert left == pytest.approx(0.0)


def test_left_in_the_picture_is_left_of_the_rover():
    forward, left = to_mm((260.0, 480.0), ORIGIN, 1.5)  # 60 pixels to the left

    assert forward == pytest.approx(0.0)
    assert left == pytest.approx(40.0)


def test_millimetres_and_pixels_convert_back_and_forth():
    point = (123.0, 234.0)

    assert to_px(to_mm(point, ORIGIN, 1.5), ORIGIN, 1.5) == pytest.approx(point)


@pytest.mark.parametrize("bad", [0.0, -1.0])
def test_a_zero_or_negative_scale_is_rejected(bad):
    with pytest.raises(ValueError):
        to_mm((0.0, 0.0), ORIGIN, bad)
    with pytest.raises(ValueError):
        to_px((0.0, 0.0), ORIGIN, bad)


@pytest.mark.parametrize("kwargs", [{"block_mm": 0.0}, {"window": 0}, {"min_samples": 0}])
def test_nonsense_estimator_settings_are_rejected(kwargs):
    with pytest.raises(ValueError):
        ScaleEstimator(**kwargs)
