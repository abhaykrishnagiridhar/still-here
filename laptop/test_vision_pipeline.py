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
