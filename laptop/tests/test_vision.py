import cv2
import numpy as np
import pytest

from models import Block
from planner import plan
from vision import (
    SurvivorFinder,
    Tracker,
    describe_plan,
    draw_overlay,
    exclude_near,
    find_blob_centres,
    fire_mask,
    parse_args,
    plan_signature,
    red_mask,
)

RED = (0, 0, 255)  # BGR
PINK_RED = (60, 0, 255)  # hue near the top of the range, on the far side of the wrap
ORANGE_FIRE = (0, 200, 255)
DARK_WOOD = (30, 80, 150)


def canvas(size=200):
    return np.zeros((size, size, 3), dtype=np.uint8)


def hsv_of(image):
    return cv2.cvtColor(image, cv2.COLOR_BGR2HSV)


def with_box(image, top_left, bottom_right, colour):
    out = image.copy()
    cv2.rectangle(out, top_left, bottom_right, colour, thickness=-1)
    return out


def test_a_red_block_is_found_at_its_centre():
    image = with_box(canvas(), (50, 60), (90, 100), RED)

    centres = find_blob_centres(red_mask(hsv_of(image)), min_area=400)

    assert len(centres) == 1
    x, y = centres[0]
    assert abs(x - 70) <= 2 and abs(y - 80) <= 2


def test_red_on_the_far_side_of_the_hue_wrap_is_found_too():
    image = with_box(canvas(), (50, 60), (90, 100), PINK_RED)

    centres = find_blob_centres(red_mask(hsv_of(image)), min_area=400)

    assert len(centres) == 1


def test_a_tiny_red_speck_is_ignored():
    image = with_box(canvas(), (50, 60), (60, 70), RED)

    assert find_blob_centres(red_mask(hsv_of(image)), min_area=400) == []


def test_a_red_region_bigger_than_the_maximum_is_ignored():
    image = with_box(canvas(), (10, 10), (160, 160), RED)

    centres = find_blob_centres(red_mask(hsv_of(image)), min_area=400, max_area=10000)

    assert centres == []


def test_two_separate_blocks_give_two_centres():
    image = with_box(canvas(), (20, 20), (60, 60), RED)
    image = with_box(image, (120, 120), (160, 160), RED)

    centres = find_blob_centres(red_mask(hsv_of(image)), min_area=400)

    assert len(centres) == 2


def test_bright_orange_counts_as_fire_but_dark_wood_and_red_do_not():
    fire = with_box(canvas(), (50, 50), (120, 120), ORANGE_FIRE)
    wood = with_box(canvas(), (50, 50), (120, 120), DARK_WOOD)
    red = with_box(canvas(), (50, 50), (120, 120), RED)

    assert find_blob_centres(fire_mask(hsv_of(fire)), min_area=800) != []
    assert find_blob_centres(fire_mask(hsv_of(wood)), min_area=800) == []
    assert find_blob_centres(fire_mask(hsv_of(red)), min_area=800) == []


def test_a_blob_is_only_believed_after_three_frames_in_a_row():
    tracker = Tracker(confirm_frames=3)

    assert tracker.update([(100, 100)]) == ()
    assert tracker.update([(100, 100)]) == ()
    confirmed = tracker.update([(100, 100)])

    assert len(confirmed) == 1


def test_a_block_keeps_its_id_while_it_jitters_a_little():
    tracker = Tracker(confirm_frames=2)
    tracker.update([(100, 100)])
    first = tracker.update([(101, 99)])
    second = tracker.update([(103, 100)])

    assert first[0].id == second[0].id


def test_two_blocks_get_different_ids():
    tracker = Tracker(confirm_frames=1)

    tracks = tracker.update([(50, 50), (200, 200)])

    assert len({t.id for t in tracks}) == 2


def test_a_confirmed_block_survives_a_few_missed_frames_then_is_dropped():
    tracker = Tracker(confirm_frames=1, max_missing=2)
    tracker.update([(100, 100)])

    assert len(tracker.update([])) == 1
    assert len(tracker.update([])) == 1
    assert tracker.update([]) == ()


def test_a_new_blob_far_away_is_a_new_block_not_the_old_one_moving():
    tracker = Tracker(confirm_frames=1, max_distance=40)
    old = tracker.update([(100, 100)])
    both = tracker.update([(100, 100), (300, 300)])

    assert len(both) == 2
    assert old[0].id in {t.id for t in both}


def test_the_plan_signature_ignores_small_position_changes():
    a = Block(id=1, marker_id=1, x=100.0, y=100.0, layer=1)
    b = Block(id=1, marker_id=1, x=101.0, y=99.0, layer=1)

    assert plan_signature(plan([a])) == plan_signature(plan([b]))


def test_the_plan_signature_changes_when_the_plan_really_changes():
    light = Block(id=1, marker_id=1, x=0.0, y=0.0, layer=1)
    heavy = Block(id=1, marker_id=1, x=0.0, y=0.0, layer=1, weight_class="heavy")

    assert plan_signature(plan([light])) != plan_signature(plan([heavy]))


def test_the_description_names_picks_and_blocks_left_in_place():
    picked = Block(id=2, marker_id=2, x=5.0, y=6.0, layer=1)
    heavy = Block(id=3, marker_id=3, x=0.0, y=0.0, layer=1, weight_class="heavy")

    text = describe_plan(plan([picked, heavy]))

    assert "Pick 1" in text and "block_2" in text
    assert "Leave block_3" in text and "heavy block" in text


def test_an_empty_scene_says_no_blocks_were_seen_not_that_none_are_safe():
    assert "No blocks seen" in describe_plan(plan([]))


def test_a_long_thin_red_strip_is_not_a_block_but_a_square_is():
    strip = with_box(canvas(), (30, 90), (150, 110), RED)
    square = with_box(canvas(), (60, 60), (100, 100), RED)

    assert find_blob_centres(red_mask(hsv_of(strip)), min_area=400, max_aspect=2.0) == []
    assert len(find_blob_centres(red_mask(hsv_of(square)), min_area=400, max_aspect=2.0)) == 1


def gray_frame(squares=(), size=240):
    frame = np.zeros((size, size), dtype=np.uint8)
    for x, y, half, value in squares:
        cv2.rectangle(frame, (x - half, y - half), (x + half, y + half), value, -1)
    return frame


def feed(finder, frames, fps=30.0):
    result = None
    for index, frame in enumerate(frames):
        result = finder.update(frame, index / fps)
    return result


def blinking_frames(position, count=60, on_frames=10):
    """A light that is on for on_frames, off for on_frames, over and over (1.5 Hz at 30 fps)."""
    x, y = position
    return [
        gray_frame([(x, y, 12, 255)] if (i // on_frames) % 2 == 0 else [])
        for i in range(count)
    ]


def test_a_pulsing_light_is_found_where_it_is():
    found = feed(SurvivorFinder(), blinking_frames((100, 80)))

    assert found is not None
    assert abs(found[0] - 100) <= 8 and abs(found[1] - 80) <= 8


def test_a_steady_light_is_not_the_survivor():
    frames = [gray_frame([(100, 80, 12, 255)]) for _ in range(60)]

    assert feed(SurvivorFinder(), frames) is None


def test_a_light_that_flashes_only_once_is_not_the_survivor():
    frames = [
        gray_frame([(100, 80, 12, 255)] if 25 <= i <= 30 else []) for i in range(60)
    ]

    assert feed(SurvivorFinder(), frames) is None


def test_nothing_is_reported_before_enough_frames_have_arrived():
    assert feed(SurvivorFinder(), blinking_frames((100, 80), count=3)) is None


def test_the_pulsing_light_is_picked_out_from_a_steady_one():
    frames = [
        gray_frame(([(60, 60, 12, 255)] if (i // 10) % 2 == 0 else []) + [(180, 180, 12, 255)])
        for i in range(60)
    ]

    found = feed(SurvivorFinder(), frames)

    assert found is not None
    assert abs(found[0] - 60) <= 8 and abs(found[1] - 60) <= 8


def test_points_near_a_centre_are_dropped_and_far_ones_kept():
    points = [(100, 100), (110, 100), (300, 300)]

    assert exclude_near(points, (100, 100), radius=30) == [(300, 300)]


def test_the_overlay_marks_the_survivor_light():
    drawn = draw_overlay(canvas(), plan([]), [], survivor=(50, 60))

    assert drawn.any()


def test_the_description_and_signature_include_the_survivor():
    result = plan([])

    assert "Survivor light at (50, 60)" in describe_plan(result, survivor=(50, 60))
    assert plan_signature(result, survivor_seen=True) != plan_signature(result)


def test_command_line_options():
    assert parse_args([]) == ("0", False)
    assert parse_args(["1"]) == ("1", False)
    assert parse_args(["http://192.168.0.50/stream", "--masks"]) == (
        "http://192.168.0.50/stream",
        True,
    )
    assert parse_args(["--masks"]) == ("0", True)
    with pytest.raises(ValueError):
        parse_args(["--nonsense"])


def test_drawing_the_overlay_returns_a_new_frame_and_leaves_the_original_alone():
    frame = canvas()
    result = plan([Block(id=1, marker_id=1, x=100.0, y=100.0, layer=1)])

    drawn = draw_overlay(frame, result, [])

    assert not frame.any()
    assert drawn.any()
