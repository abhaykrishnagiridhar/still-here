"""Finding the survivor in a picture from the Blender twin: the model's boxes and the simulation's own."""

import json
import socket
import threading

import cv2
import numpy as np
import pytest

import survivor_check
from person_detector import Detection
from snapshot_protocol import parse_snapshot
from survivor_check import Finding, annotate, decide, load_truth, request_snapshot

MODEL_BOX = Detection(100.0, 50.0, 60.0, 180.0, 0.8)
TRUTH_BOX = Detection(102.0, 52.0, 58.0, 176.0, 1.0)


def picture(width=320, height=240):
    return np.full((height, width, 3), 90, dtype=np.uint8)


class FakeDetector:
    def __init__(self, boxes):
        self.boxes = boxes

    def detect(self, image):
        return list(self.boxes)


# ---- deciding who found the survivor ------------------------------------------------------


def test_the_simulations_truth_wins_and_says_whether_the_model_agrees():
    finding = decide([MODEL_BOX], TRUTH_BOX)

    assert finding == Finding("simulation", TRUTH_BOX, model_agrees=True)


def test_a_model_that_sees_something_else_is_reported_as_disagreeing():
    elsewhere = Detection(500.0, 300.0, 40.0, 100.0, 0.9)

    assert decide([elsewhere], TRUTH_BOX).model_agrees is False
    assert decide([], TRUTH_BOX).model_agrees is False


def test_without_truth_the_models_strongest_box_is_used():
    weak, strong = Detection(0, 0, 10, 20, 0.4), Detection(50, 50, 30, 60, 0.9)

    finding = decide([weak, strong], None)

    assert finding.source == "model" and finding.box is strong and finding.model_agrees is None


def test_nobody_found_is_none():
    assert decide([], None) is None


def test_the_survivor_point_is_where_the_person_stands():
    finding = Finding("model", Detection(100.0, 50.0, 40.0, 120.0, 0.9), None)

    assert finding.survivor_px == (120, 170)


# ---- the sidecar file ---------------------------------------------------------------------


def test_the_truth_file_gives_a_box(tmp_path):
    path = tmp_path / "view.json"
    path.write_text(json.dumps({"survivor_box": {"x": 10, "y": 20, "w": 30, "h": 40}}), encoding="utf-8")

    box = load_truth(path)

    assert (box.x, box.y, box.w, box.h) == (10, 20, 30, 40)


@pytest.mark.parametrize(
    "text",
    ['{"survivor_box": null}', "{}", "not json", '{"survivor_box": {"x": 1}}', '{"survivor_box": {"x": "a", "y": 1, "w": 2, "h": 3}}'],
)
def test_a_truth_file_without_a_usable_box_gives_nothing(tmp_path, text):
    path = tmp_path / "view.json"
    path.write_text(text, encoding="utf-8")

    assert load_truth(path) is None


def test_a_missing_truth_file_gives_nothing(tmp_path):
    assert load_truth(tmp_path / "nope.json") is None


# ---- asking Blender -----------------------------------------------------------------------


class FakeBlender(threading.Thread):
    """Listens on a UDP port like blender_rover.py and answers a snapshot request."""

    def __init__(self, frames_dir, box=None):
        super().__init__(daemon=True)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.settimeout(3.0)
        self.port = self.sock.getsockname()[1]
        self.frames_dir = frames_dir
        self.box = box

    def run(self):
        try:
            raw, _ = self.sock.recvfrom(4096)
        except OSError:
            return
        request = parse_snapshot(json.loads(raw), self.frames_dir)
        cv2.imwrite(str(request.path), picture(64, 48))
        request.path.with_suffix(".json").write_text(
            json.dumps({"survivor_box": self.box}), encoding="utf-8"
        )


def test_a_snapshot_request_comes_back_with_the_picture_and_the_truth(tmp_path):
    blender = FakeBlender(tmp_path, {"x": 5, "y": 6, "w": 7, "h": 8})
    blender.start()

    image, truth = request_snapshot(tmp_path / "view.png", "rover", "127.0.0.1", blender.port, wait_s=3.0)

    assert image.shape == (48, 64, 3)
    assert (truth.x, truth.y, truth.w, truth.h) == (5, 6, 7, 8)


def test_a_silent_blender_gives_a_clear_timeout(tmp_path):
    silent = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    silent.bind(("127.0.0.1", 0))
    try:
        with pytest.raises(TimeoutError, match="blender_rover.py"):
            request_snapshot(tmp_path / "view.png", "rover", "127.0.0.1", silent.getsockname()[1], wait_s=0.3)
    finally:
        silent.close()


def test_an_old_picture_is_not_mistaken_for_the_new_one(tmp_path):
    cv2.imwrite(str(tmp_path / "view.png"), picture(10, 10))
    (tmp_path / "view.json").write_text("{}", encoding="utf-8")
    silent = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    silent.bind(("127.0.0.1", 0))
    try:
        with pytest.raises(TimeoutError):
            request_snapshot(tmp_path / "view.png", "rover", "127.0.0.1", silent.getsockname()[1], wait_s=0.3)
    finally:
        silent.close()


# ---- drawing and the command line ---------------------------------------------------------


def test_annotate_marks_the_picture_without_changing_its_size():
    image = picture()
    marked = annotate(image, decide([MODEL_BOX], TRUTH_BOX), [MODEL_BOX])

    assert marked.shape == image.shape
    assert (marked != image).any()
    assert (image == 90).all()  # the original is left alone


def test_the_command_line_reports_the_survivor_as_json(tmp_path, capsys):
    image_path = tmp_path / "view.png"
    cv2.imwrite(str(image_path), picture())
    image_path.with_suffix(".json").write_text(
        json.dumps({"survivor_box": {"x": 100, "y": 50, "w": 60, "h": 180}}), encoding="utf-8"
    )

    code = survivor_check.main(
        ["--image", str(image_path), "--out", str(tmp_path / "marked.png")],
        detector=FakeDetector([MODEL_BOX]),
    )

    report = json.loads(capsys.readouterr().out)
    assert code == 0
    assert report["source"] == "simulation" and report["model_agrees"] is True
    assert report["survivor_px"] == [130, 230]
    assert (tmp_path / "marked.png").exists()


def test_the_command_line_exits_with_one_when_nobody_is_found(tmp_path, capsys):
    image_path = tmp_path / "view.png"
    cv2.imwrite(str(image_path), picture())

    code = survivor_check.main(["--image", str(image_path), "--out", str(tmp_path / "m.png")], detector=FakeDetector([]))

    assert code == 1
    assert json.loads(capsys.readouterr().out)["source"] is None
