"""Finds people in a picture with a pretrained YOLOX-S network, run by OpenCV (no PyTorch needed).

It is used for the survivor when the survivor is a person or a doll rather than a pulsing light, and
it works on any picture: the rover's camera, the laptop webcam, or a picture rendered from the Blender
simulation. The model file is the int8 YOLOX-S from the OpenCV model zoo
(https://github.com/opencv/opencv_zoo, models/object_detection_yolox, Apache-2.0). It is kept in
laptop/models/ and is not part of git.

    detector = PersonDetector("models/object_detection_yolox_2022nov_int8.onnx")
    people = detector.detect(picture)          # boxes in the picture's own pixels
    survivor = strongest(people)

A picture takes about 0.3 s on a laptop CPU, so run it a few times a second, not on every frame.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

import cv2
import numpy as np

INPUT_SIZE = 640
STRIDES = (8, 16, 32)
CANDIDATES = sum((INPUT_SIZE // s) ** 2 for s in STRIDES)  # 8400
VALUES_PER_CANDIDATE = 85  # x, y, w, h, objectness, then 80 class scores
PERSON_CLASS = 0
PAD_VALUE = 114
DEFAULT_CONFIDENCE = 0.4
DEFAULT_NMS = 0.45


@dataclass(frozen=True)
class Detection:
    x: float  # top-left corner
    y: float
    w: float
    h: float
    score: float

    @property
    def centre(self) -> tuple[float, float]:
        return (self.x + self.w / 2, self.y + self.h / 2)

    @property
    def foot(self) -> tuple[float, float]:
        """The middle of the bottom edge: where the person touches the ground."""
        return (self.x + self.w / 2, self.y + self.h)


def letterbox(image: np.ndarray, size: int = INPUT_SIZE) -> tuple[np.ndarray, float]:
    """Shrink or grow the picture to fit a size-by-size square without bending it, padding the rest
    with grey. Returns the square and the scale that was applied."""
    height, width = image.shape[:2]
    ratio = min(size / height, size / width)
    resized = cv2.resize(image, (max(1, int(width * ratio)), max(1, int(height * ratio))))
    canvas = np.full((size, size, 3), PAD_VALUE, dtype=np.uint8)
    canvas[: resized.shape[0], : resized.shape[1]] = resized
    return canvas, ratio


def _grid() -> tuple[np.ndarray, np.ndarray]:
    """For every candidate, the grid cell it sits in and the stride of its layer."""
    cells, strides = [], []
    for stride in STRIDES:
        n = INPUT_SIZE // stride
        xs, ys = np.meshgrid(np.arange(n), np.arange(n))
        cells.append(np.stack((xs, ys), axis=-1).reshape(-1, 2))
        strides.append(np.full((n * n, 1), stride))
    return np.concatenate(cells).astype(np.float32), np.concatenate(strides).astype(np.float32)


_CELLS, _STRIDE = _grid()


def decode_yolox(
    output: np.ndarray,
    ratio: float,
    image_shape: tuple[int, int],
    conf: float = DEFAULT_CONFIDENCE,
    nms: float = DEFAULT_NMS,
) -> list[Detection]:
    """Turn the network's raw output into boxes around people, in the original picture's pixels."""
    if output.ndim != 3 or output.shape[1] != CANDIDATES or output.shape[2] != VALUES_PER_CANDIDATE:
        raise ValueError(f"expected output of shape (1, {CANDIDATES}, {VALUES_PER_CANDIDATE}), got {output.shape}")
    raw = output[0]
    scores = raw[:, 4] * raw[:, 5 + PERSON_CLASS]
    keep = np.flatnonzero(scores >= conf)
    if keep.size == 0:
        return []

    centre = (raw[keep, 0:2] + _CELLS[keep]) * _STRIDE[keep]
    size = np.exp(raw[keep, 2:4]) * _STRIDE[keep]
    corner = (centre - size / 2) / ratio
    size = size / ratio

    height, width = image_shape
    x0 = np.clip(corner[:, 0], 0, width)
    y0 = np.clip(corner[:, 1], 0, height)
    x1 = np.clip(corner[:, 0] + size[:, 0], 0, width)
    y1 = np.clip(corner[:, 1] + size[:, 1], 0, height)
    boxes = [[float(a), float(b), float(c - a), float(d - b)] for a, b, c, d in zip(x0, y0, x1, y1)]
    kept_scores = [float(s) for s in scores[keep]]

    survivors = cv2.dnn.NMSBoxes(boxes, kept_scores, conf, nms)
    order = sorted((int(i) for i in np.array(survivors).flatten()), key=lambda i: -kept_scores[i])
    return [Detection(*boxes[i], kept_scores[i]) for i in order if boxes[i][2] > 0 and boxes[i][3] > 0]


def strongest(detections: Sequence[Detection]) -> Optional[Detection]:
    """The most confident detection, or None when nobody was found."""
    return max(detections, key=lambda d: d.score) if detections else None


class PersonDetector:
    def __init__(
        self,
        model_path=None,
        *,
        net=None,
        conf: float = DEFAULT_CONFIDENCE,
        nms: float = DEFAULT_NMS,
        swap_rb: bool = False,
    ) -> None:
        if net is None:
            if model_path is None or not Path(model_path).is_file():
                raise FileNotFoundError(f"the person detector model was not found: {model_path}")
            # OpenCV 5's new default engine returns all zeros for this quantised model, so ask for the
            # classic one (older OpenCV versions have no choice to make).
            engine = getattr(cv2.dnn, "ENGINE_CLASSIC", None)
            net = cv2.dnn.readNetFromONNX(str(model_path), engine) if engine is not None else cv2.dnn.readNetFromONNX(str(model_path))
        self._net = net
        self._conf = conf
        self._nms = nms
        self._swap_rb = swap_rb

    def detect(self, image: np.ndarray) -> list[Detection]:
        """People in a BGR picture, strongest first. An empty picture has nobody in it."""
        if image is None or image.size == 0:
            return []
        padded, ratio = letterbox(image)
        blob = cv2.dnn.blobFromImage(padded, 1.0, (INPUT_SIZE, INPUT_SIZE), swapRB=self._swap_rb)
        self._net.setInput(blob)
        return decode_yolox(self._net.forward(), ratio, image.shape[:2], self._conf, self._nms)
