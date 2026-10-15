"""The whole camera pipeline on made-up pictures: blocks, the 40 mm scale, fire, the survivor."""

import cv2
import numpy as np
import pytest

import vision
from route import RoutePlan
from vision import Pipeline

RED = (0, 0, 255)  # BGR
FIRE = (0, 200, 255)  # bright orange
AMBER_LED = (0, 200, 255)
BLOCKS = ((150, 200), (300, 300), (450, 200))  # centres, in pixels; each 60 pixels wide
FPS = 30.0


def frame_with(blocks=BLOCKS, fire=None, big_red=None, led=None):
    image = np.zeros((480, 640, 3), dtype=np.uint8)
    for cx, cy in blocks:
        cv2.rectangle(image, (cx - 30, cy - 30), (cx + 30, cy + 30), RED, -1)
    if big_red:
        cx, cy = big_red
        cv2.rectangle(image, (cx - 75, cy - 75), (cx + 75, cy + 75), RED, -1)
    if fire:
        cx, cy = fire
        cv2.rectangle(image, (cx - 35, cy - 35), (cx + 35, cy + 35), FIRE, -1)
    if led:
        cv2.circle(image, led, 8, AMBER_LED, -1)
    return image


def run_pipeline(seconds=2.0, blink_at=None, **scene):
    """Feed the same scene for a while; return the pipeline and every report it printed."""
    pipeline = Pipeline()
    reports = []
    last = None
    for i in range(int(seconds * FPS)):
        led = blink_at if blink_at is not None and (i // 10) % 2 == 0 else None
        last = pipeline.process(frame_with(led=led, **scene), i / FPS)
        if last.report:
            reports.append(last.report)
    return pipeline, last, reports


def test_nothing_is_planned_before_the_size_of_a_block_is_known():
    pipeline = Pipeline()

    first = pipeline.process(frame_with(), 0.0)

    assert pipeline.px_per_mm is None
    assert first.report is None
    assert first.result is None
    assert first.shown.shape == (480, 640, 3)


def test_the_blocks_set_the_scale_at_1_point_5_pixels_per_millimetre():
    pipeline, _, _ = run_pipeline()

    assert pipeline.px_per_mm == pytest.approx(1.5, rel=0.05)


def test_blocks_are_planned_and_reported_in_millimetres():
    pipeline, last, reports = run_pipeline()

    assert len(last.result.order) == 3
    assert reports and "Pick 1" in reports[-1]
    assert "mm" in reports[-1]
    # The block at pixel (300, 300) is 180 pixels ahead of the rover and 20 pixels to the left,
    # converted with the scale the blocks themselves gave.
    scale = pipeline.px_per_mm
    assert f"at ({180 / scale:.0f}, {20 / scale:.0f}) mm" in reports[-1]


def test_a_table_sized_red_region_is_not_taken_for_a_block():
    _, last, _ = run_pipeline(big_red=(560, 400))

    assert len(last.result.order) == 3


def test_a_steady_fire_makes_the_block_next_to_it_stay():
    _, last, reports = run_pipeline(fire=(130, 340))

    assert [item.block.id for item in last.result.left] == [1]
    assert "near heat" in reports[-1]


def test_a_blinking_light_is_the_survivor_and_the_route_is_used():
    _, last, reports = run_pipeline(seconds=3.0, blink_at=(320, 100))

    assert isinstance(last.result, RoutePlan)
    assert "Survivor light at" in reports[-1]
    assert last.result.ok


def test_a_survivor_the_operator_tapped_is_used_without_any_pulsing():
    pipeline = Pipeline()
    last = None
    for i in range(int(2.0 * FPS)):
        last = pipeline.process(frame_with(), i / FPS, survivor_hint=(320, 100))

    assert isinstance(last.result, RoutePlan)
    assert last.survivor == (320, 100)
    assert last.scene.survivor is not None


def test_the_frame_result_carries_what_the_operator_page_needs_to_convert_taps():
    pipeline, last, _ = run_pipeline()

    assert last.origin == (320.0, 480.0)
    assert last.px_per_mm == pytest.approx(pipeline.px_per_mm)
    assert len(last.scene.blocks) == 3
    assert last.survivor is None


def test_the_report_is_only_printed_when_the_plan_changes():
    _, _, reports = run_pipeline(seconds=3.0)

    assert len(reports) == 1


def test_run_plays_a_video_file_to_the_end_and_prints_the_plan(tmp_path, capsys, monkeypatch):
    path = str(tmp_path / "scene.avi")
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"MJPG"), FPS, (640, 480))
    for _ in range(90):
        writer.write(frame_with())
    writer.release()
    monkeypatch.setattr(vision.cv2, "imshow", lambda *args: None)
    monkeypatch.setattr(vision.cv2, "waitKey", lambda *args: -1)
    monkeypatch.setattr(vision.cv2, "destroyAllWindows", lambda: None)

    code = vision.run(path)

    printed = capsys.readouterr().out
    assert code == 0
    assert "Pick 1" in printed and "mm" in printed


def marker_frame(markers):
    """A white picture with markers pasted in: (id, centre_x, centre_y), each 60 pixels wide."""
    image = np.full((480, 640, 3), 255, dtype=np.uint8)
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    for marker_id, cx, cy in markers:
        tile = cv2.cvtColor(cv2.aruco.generateImageMarker(dictionary, marker_id, 60), cv2.COLOR_GRAY2BGR)
        image[cy - 30 : cy + 30, cx - 30 : cx + 30] = tile
    return image


def run_markers(markers, seconds=2.0, config=None):
    pipeline = Pipeline(config=config)
    reports, last = [], None
    for i in range(int(seconds * FPS)):
        last = pipeline.process(marker_frame(markers), i / FPS)
        if last.report:
            reports.append(last.report)
    return pipeline, last, reports


# Marker 5 is a top block resting on bottom block 2 (its marker sits one block height higher), marker 9 is heavy, marker 3 stands alone.
STACK = [(2, 300, 300), (5, 300, 236), (9, 150, 200), (3, 450, 200)]


def test_markers_set_the_scale_from_the_printed_marker_size():
    pipeline, _, _ = run_markers(STACK)

    assert pipeline.px_per_mm == pytest.approx(2.0, rel=0.05)  # 60 pixels for a 30 mm marker


def test_the_top_block_is_picked_before_the_block_it_rests_on():
    _, last, _ = run_markers(STACK)

    order = [b.id for b in last.result.order]
    assert order.index(5) < order.index(2)


def test_a_heavy_marker_is_left_where_it_is():
    _, last, reports = run_markers(STACK)

    assert [(item.block.id, item.reason) for item in last.result.left] == [(9, "heavy block")]
    assert "heavy block" in reports[-1]


def test_markers_are_reported_by_their_ids_in_millimetres():
    _, _, reports = run_markers(STACK)

    assert "block_5" in reports[-1]
    assert "mm" in reports[-1]


def test_a_changed_config_changes_what_the_ids_mean():
    from aruco import Config

    _, last, _ = run_markers(STACK, config=Config(heavy_marker_ids=(3,), top_marker_ids=(5,)))

    assert [item.block.id for item in last.result.left] == [3]


def test_a_marker_that_blinks_out_for_a_moment_does_not_change_the_plan():
    pipeline = Pipeline()
    for i in range(60):
        pipeline.process(marker_frame(STACK), i / FPS)

    gap = pipeline.process(marker_frame([m for m in STACK if m[0] != 3]), 60 / FPS)

    assert 3 in [b.id for b in gap.result.order]


def test_with_no_markers_in_view_the_red_blocks_are_used():
    _, last, _ = run_pipeline()

    assert len(last.result.order) == 3


class DeadCamera:
    """A network camera that never answers. No real connection is made."""

    def isOpened(self):
        return False

    def read(self):
        return False, None

    def release(self):
        pass


def test_run_reports_a_source_that_cannot_be_opened(capsys, monkeypatch):
    monkeypatch.setattr(vision, "open_source", lambda source: DeadCamera())
    monkeypatch.setattr(vision.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(vision.cv2, "waitKey", lambda *args: -1)
    monkeypatch.setattr(vision.cv2, "destroyAllWindows", lambda: None)

    code = vision.run("http://192.168.0.50/stream")

    assert code == 1
    assert "video source" in capsys.readouterr().err
