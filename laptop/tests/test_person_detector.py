"""The pretrained person detector: picture in, boxes around people out."""

from pathlib import Path

import numpy as np
import pytest

from person_detector import (
    Detection,
    PersonDetector,
    decode_yolox,
    letterbox,
    strongest,
)

SIZE = 640
STRIDES = (8, 16, 32)
MODEL = Path(__file__).resolve().parents[1] / "models" / "object_detection_yolox_2022nov_int8.onnx"


def blank_output():
    return np.zeros((1, 8400, 85), dtype=np.float32)


def set_cell(out, stride_index, gx, gy, cx, cy, w, h, objectness=0.9, cls=0, cls_score=0.9):
    """Write one candidate the way YOLOX does: offsets from a grid cell, sizes as logs."""
    sizes = [(SIZE // s) ** 2 for s in STRIDES]
    start = sum(sizes[:stride_index])
    grid = SIZE // STRIDES[stride_index]
    stride = STRIDES[stride_index]
    index = start + gy * grid + gx
    out[0, index, 0] = (cx / stride) - gx
    out[0, index, 1] = (cy / stride) - gy
    out[0, index, 2] = np.log(w / stride)
    out[0, index, 3] = np.log(h / stride)
    out[0, index, 4] = objectness
    out[0, index, 5 + cls] = cls_score


# ---- letterbox ----------------------------------------------------------------------------


def test_letterbox_keeps_the_aspect_ratio_and_pads_with_grey():
    image = np.zeros((300, 400, 3), dtype=np.uint8)

    padded, ratio = letterbox(image, 640)

    assert padded.shape == (640, 640, 3)
    assert ratio == pytest.approx(1.6)
    assert padded[-1, -1].tolist() == [114, 114, 114]


def test_letterbox_scales_a_tall_picture_by_its_height():
    padded, ratio = letterbox(np.zeros((960, 480, 3), dtype=np.uint8), 640)

    assert ratio == pytest.approx(640 / 960)
    assert padded.shape == (640, 640, 3)


# ---- decoding -----------------------------------------------------------------------------


def test_a_confident_person_cell_becomes_one_box_in_picture_pixels():
    out = blank_output()
    set_cell(out, 0, gx=20, gy=30, cx=164.0, cy=244.0, w=80.0, h=160.0)

    boxes = decode_yolox(out, ratio=1.0, image_shape=(640, 640), conf=0.4)

    assert len(boxes) == 1
    box = boxes[0]
    assert (box.x, box.y, box.w, box.h) == pytest.approx((124.0, 164.0, 80.0, 160.0), abs=0.5)
    assert box.score == pytest.approx(0.81, abs=0.01)


def test_the_ratio_maps_boxes_back_to_the_original_picture():
    out = blank_output()
    set_cell(out, 1, gx=10, gy=10, cx=168.0, cy=168.0, w=64.0, h=128.0)

    box = decode_yolox(out, ratio=2.0, image_shape=(640, 640), conf=0.4)[0]

    assert (box.x, box.y, box.w, box.h) == pytest.approx((68.0, 52.0, 32.0, 64.0), abs=0.5)


def test_things_that_are_not_people_are_ignored():
    out = blank_output()
    set_cell(out, 0, 20, 30, 164.0, 244.0, 80.0, 160.0, cls=2)  # class 2 is a car

    assert decode_yolox(out, ratio=1.0, image_shape=(640, 640), conf=0.4) == []


def test_weak_candidates_are_dropped():
    out = blank_output()
    set_cell(out, 0, 20, 30, 164.0, 244.0, 80.0, 160.0, objectness=0.5, cls_score=0.5)  # 0.25 overall

    assert decode_yolox(out, ratio=1.0, image_shape=(640, 640), conf=0.4) == []


def test_overlapping_duplicates_collapse_to_the_best_one():
    out = blank_output()
    set_cell(out, 0, 20, 30, 164.0, 244.0, 80.0, 160.0, objectness=0.95, cls_score=0.95)
    set_cell(out, 0, 21, 30, 168.0, 244.0, 80.0, 160.0, objectness=0.8, cls_score=0.8)

    boxes = decode_yolox(out, ratio=1.0, image_shape=(640, 640), conf=0.4, nms=0.45)

    assert len(boxes) == 1
    assert boxes[0].score == pytest.approx(0.9025, abs=0.01)


def test_two_separate_people_are_both_kept():
    out = blank_output()
    set_cell(out, 0, 10, 20, 84.0, 164.0, 60.0, 120.0)
    set_cell(out, 0, 60, 20, 484.0, 164.0, 60.0, 120.0)

    assert len(decode_yolox(out, ratio=1.0, image_shape=(640, 640), conf=0.4)) == 2


def test_boxes_are_kept_inside_the_picture():
    out = blank_output()
    set_cell(out, 0, 1, 1, 8.0, 8.0, 80.0, 80.0)

    box = decode_yolox(out, ratio=1.0, image_shape=(480, 640), conf=0.4)[0]

    assert box.x >= 0 and box.y >= 0
    assert box.x + box.w <= 640 and box.y + box.h <= 480


def test_a_wrongly_shaped_output_is_refused():
    with pytest.raises(ValueError):
        decode_yolox(np.zeros((1, 100, 85), dtype=np.float32), 1.0, (640, 640), 0.4)


# ---- the detector -------------------------------------------------------------------------


class FakeNet:
    def __init__(self, output):
        self.output = output
        self.seen = None

    def setInput(self, blob):
        self.seen = blob

    def forward(self):
        return self.output


def test_detect_runs_the_net_on_a_letterboxed_picture_and_maps_boxes_back():
    out = blank_output()
    set_cell(out, 0, 20, 30, 164.0, 244.0, 80.0, 160.0)
    net = FakeNet(out)
    detector = PersonDetector(net=net)

    found = detector.detect(np.zeros((320, 640, 3), dtype=np.uint8))  # ratio 1.0, padded below

    assert net.seen.shape == (1, 3, 640, 640)
    assert len(found) == 1 and isinstance(found[0], Detection)
    assert found[0].w == pytest.approx(80.0, abs=0.5)


def test_an_empty_picture_finds_nobody():
    detector = PersonDetector(net=FakeNet(blank_output()))

    assert detector.detect(np.zeros((240, 320, 3), dtype=np.uint8)) == []
    assert detector.detect(np.zeros((0, 0, 3), dtype=np.uint8)) == []


def test_strongest_picks_the_highest_score_and_none_for_nobody():
    a, b = Detection(0, 0, 10, 10, 0.5), Detection(5, 5, 10, 10, 0.9)

    assert strongest([a, b]) is b
    assert strongest([]) is None


def test_the_detection_gives_its_centre_and_foot_point():
    box = Detection(100.0, 50.0, 40.0, 120.0, 0.9)

    assert box.centre == (120.0, 110.0)
    assert box.foot == (120.0, 170.0)


@pytest.mark.skipif(not MODEL.exists(), reason="the YOLOX model file has not been downloaded")
def test_the_real_model_sees_nobody_in_a_blank_picture():
    detector = PersonDetector(MODEL)

    assert detector.detect(np.full((296, 400, 3), 40, dtype=np.uint8)) == []


@pytest.mark.skipif(not MODEL.exists(), reason="the YOLOX model file has not been downloaded")
def test_the_real_model_gives_real_scores_not_the_all_zero_output_of_the_wrong_engine():
    detector = PersonDetector(MODEL)
    noise = np.random.default_rng(0).integers(0, 255, (640, 640, 3), dtype=np.uint8)
    detector._net.setInput(__import__("cv2").dnn.blobFromImage(noise, 1.0, (640, 640)))

    raw = detector._net.forward()

    assert raw[0, :, 4].max() > 0.0  # objectness: all zeros means OpenCV ran the model wrongly
