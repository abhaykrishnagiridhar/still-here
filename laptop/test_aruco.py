"""ArUco markers on the blocks: which block is which, top or bottom, heavy or light."""

import cv2
import numpy as np
import pytest

import aruco
from aruco import (
    BlockRules,
    Config,
    Marker,
    MarkerTracker,
    blocks_from_markers,
    find_markers,
    load_config,
)

RULES = BlockRules(top_ids=frozenset({5, 6}), heavy_ids=frozenset({9}))


def picture_with(markers, size=(480, 640)):
    """A white picture with square markers pasted in: (id, centre_x, centre_y, side) each."""
    image = np.full((*size, 3), 255, dtype=np.uint8)
    dictionary = cv2.aruco.getPredefinedDictionary(aruco.DICTIONARY)
    for marker_id, cx, cy, side in markers:
        tile = cv2.cvtColor(cv2.aruco.generateImageMarker(dictionary, marker_id, side), cv2.COLOR_GRAY2BGR)
        x0, y0 = cx - side // 2, cy - side // 2
        image[y0 : y0 + side, x0 : x0 + side] = tile
    return image


# --- finding markers ------------------------------------------------------------------


def test_a_marker_is_found_with_its_id_centre_and_size():
    image = picture_with([(7, 200, 150, 80)])

    markers = find_markers(image)

    assert len(markers) == 1
    marker = markers[0]
    assert marker.id == 7
    assert (marker.x, marker.y) == pytest.approx((200, 150), abs=1.5)
    assert marker.side == pytest.approx(80, abs=2)


def test_several_markers_are_found_in_a_stable_order():
    image = picture_with([(8, 400, 300, 60), (3, 100, 100, 60), (5, 250, 200, 60)])

    ids = [m.id for m in find_markers(image)]

    assert ids == [3, 5, 8]


def test_a_picture_with_no_markers_gives_none():
    assert find_markers(np.zeros((480, 640, 3), dtype=np.uint8)) == ()


# --- what a marker id means -----------------------------------------------------------


def test_an_id_in_the_top_list_is_a_top_layer_block_and_the_rest_are_bottom():
    blocks = blocks_from_markers([Marker(5, 100, 0, 30), Marker(2, 200, 0, 30)], RULES)

    assert {b.id: b.layer for b in blocks} == {5: 2, 2: 1}


def test_an_id_in_the_heavy_list_is_a_heavy_block():
    blocks = blocks_from_markers([Marker(9, 100, 0, 30), Marker(2, 200, 0, 30)], RULES)

    assert {b.id: b.weight_class for b in blocks} == {9: "heavy", 2: "light"}


def test_the_block_keeps_the_marker_id_and_position():
    (block,) = blocks_from_markers([Marker(2, 120.0, -30.0, 30)], RULES)

    assert (block.id, block.marker_id, block.x, block.y) == (2, 2, 120.0, -30.0)


def test_a_bottom_block_holds_up_the_top_block_sitting_on_it():
    blocks = blocks_from_markers(
        [Marker(2, 100, 0, 30), Marker(5, 105, 3, 30), Marker(3, 300, 0, 30)], RULES
    )

    by_id = {b.id: b for b in blocks}
    assert by_id[2].supports == (5,)
    assert by_id[3].supports == ()
    assert by_id[5].supports == ()


def test_a_top_block_rests_on_the_nearest_of_two_bottom_blocks():
    blocks = blocks_from_markers(
        [Marker(2, 100, 0, 30), Marker(3, 180, 0, 30), Marker(5, 150, 0, 30), Marker(6, 90, -10, 30)],
        RULES,
    )

    by_id = {b.id: b for b in blocks}
    assert by_id[2].supports == (6,)
    assert by_id[3].supports == (5,)


def test_a_top_block_far_from_every_bottom_block_rests_on_nothing():
    blocks = blocks_from_markers([Marker(2, 100, 0, 30), Marker(5, 300, 0, 30)], RULES)

    assert all(b.supports == () for b in blocks)


# --- the config file ------------------------------------------------------------------


def test_the_defaults_match_the_example_config():
    assert load_config(aruco.EXAMPLE_CONFIG) == Config()


def test_a_config_file_sets_the_block_rules(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        "[blocks]\nsize_mm = 40\nmarker_mm = 25\nheavy_marker_ids = [1, 2]\ntop_marker_ids = [3]\n"
        "[rover]\nhost = \"10.0.0.7\"\n",
        encoding="utf-8",
    )

    config = load_config(path)

    assert config.marker_mm == 25
    assert config.rules == BlockRules(top_ids=frozenset({3}), heavy_ids=frozenset({1, 2}))
    assert config.rover_host == "10.0.0.7"
    assert config.ws_port == 81  # not in the file, so the default


def test_a_missing_config_file_gives_the_defaults(tmp_path):
    assert load_config(tmp_path / "nope.toml") == Config()


def test_a_broken_config_file_says_what_is_wrong(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("[blocks]\nsize_mm = -4\n", encoding="utf-8")

    with pytest.raises(ValueError, match="size_mm"):
        load_config(path)


def test_a_marker_bigger_than_the_block_is_refused(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("[blocks]\nsize_mm = 40\nmarker_mm = 55\n", encoding="utf-8")

    with pytest.raises(ValueError, match="marker_mm"):
        load_config(path)


def test_text_that_is_not_toml_says_which_file(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("this is = = not toml", encoding="utf-8")

    with pytest.raises(ValueError, match="config.toml"):
        load_config(path)


def test_ids_that_are_not_whole_numbers_are_refused(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[blocks]\nheavy_marker_ids = ["nine"]\n', encoding="utf-8")

    with pytest.raises(ValueError, match="heavy_marker_ids"):
        load_config(path)


# --- steadiness -----------------------------------------------------------------------


def test_a_marker_that_blinks_out_for_a_few_frames_is_still_remembered():
    tracker = MarkerTracker(max_missing=3)
    seen = Marker(4, 100, 100, 50)

    tracker.update([seen])

    for _ in range(3):
        assert tracker.update([]) == (seen,)
    assert tracker.update([]) == ()


def test_a_marker_that_moves_is_reported_at_its_newest_position():
    tracker = MarkerTracker()
    tracker.update([Marker(4, 100, 100, 50)])

    assert tracker.update([Marker(4, 110, 100, 50)]) == (Marker(4, 110, 100, 50),)


def test_the_tracker_reports_markers_in_id_order():
    tracker = MarkerTracker()

    out = tracker.update([Marker(8, 0, 0, 50), Marker(3, 0, 0, 50)])

    assert [m.id for m in out] == [3, 8]
