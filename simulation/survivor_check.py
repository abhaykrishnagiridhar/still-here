"""Find the survivor in a picture from the Blender twin's rover camera.

    python simulation/survivor_check.py                  ask the running Blender twin for a picture
    python simulation/survivor_check.py --image x.png    look at a picture file instead

Two things can find the survivor:

  the model       the pretrained person detector (laptop/person_detector.py). It works on real
                  pictures of people. It does not see the twin's cartoon figure as a person.
  the simulation  Blender knows exactly where it put the figure, and writes that box next to every
                  picture (view.png, view.json). In the twin this stands in for a detector.

With a simulation box the survivor is taken from it, and the report says whether the model agreed. Without
one (a real picture) the model's strongest box is used. The result is the point where the person stands,
in picture pixels: the same kind of point the operator page gets when you tap the survivor.

Start Blender first:  blender --python simulation/blender_rover.py
"""

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

import cv2
import numpy as np

SIMULATION = Path(__file__).resolve().parent
LAPTOP = SIMULATION.parent / "laptop"
for path in (str(LAPTOP), str(SIMULATION)):
    if path not in sys.path:
        sys.path.insert(0, path)

from person_detector import Detection, PersonDetector, strongest
from snapshot_client import request_picture
from snapshot_protocol import CAMERAS

FRAMES_DIR = SIMULATION / "frames"
DEFAULT_MODEL = LAPTOP / "models" / "object_detection_yolox_2022nov_int8.onnx"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = int(os.environ.get("STILL_HERE_UDP_PORT", "8766"))
AGREEMENT_IOU = 0.3
POLL_S = 0.05


@dataclass(frozen=True)
class Finding:
    source: str  # "simulation" or "model"
    box: Detection
    model_agrees: Optional[bool]  # None when there was nothing to compare with

    @property
    def survivor_px(self) -> tuple[int, int]:
        x, y = self.box.foot
        return (round(x), round(y))


def _iou(a: Detection, b: Detection) -> float:
    left, top = max(a.x, b.x), max(a.y, b.y)
    right, bottom = min(a.x + a.w, b.x + b.w), min(a.y + a.h, b.y + b.h)
    inside = max(0.0, right - left) * max(0.0, bottom - top)
    union = a.w * a.h + b.w * b.h - inside
    return inside / union if union > 0 else 0.0


def decide(model_boxes: Sequence[Detection], truth: Optional[Detection]) -> Optional[Finding]:
    """The survivor, from the simulation's box when there is one, else from the model's best box."""
    if truth is not None:
        agrees = any(_iou(box, truth) >= AGREEMENT_IOU for box in model_boxes)
        return Finding("simulation", truth, agrees)
    best = strongest(model_boxes)
    return Finding("model", best, None) if best is not None else None


def _read_json(path: Path) -> Optional[dict]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _truth_from(data: dict) -> Optional[Detection]:
    box = data.get("survivor_box")
    if not isinstance(box, dict):
        return None
    values = [box.get(key) for key in ("x", "y", "w", "h")]
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values):
        return None
    x, y, w, h = (float(v) for v in values)
    return Detection(x, y, w, h, 1.0) if w > 0 and h > 0 else None


def load_truth(path) -> Optional[Detection]:
    """The simulation's box for the survivor from a view.json file, or None when there is not a usable one."""
    data = _read_json(Path(path))
    return _truth_from(data) if data is not None else None


def request_snapshot(
    path,
    camera: str = "rover",
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    wait_s: float = 8.0,
) -> tuple[np.ndarray, Optional[Detection]]:
    """Ask the Blender twin for a picture. Returns it and the simulation's box for the survivor (or None)."""
    result = request_picture(path, camera, host, port, wait_s)
    if result is None:
        raise TimeoutError(
            f"Blender did not answer on UDP {host}:{port}. Is simulation/blender_rover.py running in Blender? "
            "(Blender is only listening while its window is open.)"
        )
    image, sidecar = result
    return image, _truth_from(sidecar)


def annotate(image: np.ndarray, finding: Optional[Finding], model_boxes: Sequence[Detection]) -> np.ndarray:
    """A copy of the picture with the model's boxes (green) and the survivor (orange) drawn on it."""
    marked = image.copy()
    for box in model_boxes:
        top_left, bottom_right = (round(box.x), round(box.y)), (round(box.x + box.w), round(box.y + box.h))
        cv2.rectangle(marked, top_left, bottom_right, (80, 200, 80), 2)
        cv2.putText(marked, f"model {box.score:.2f}", (top_left[0], max(12, top_left[1] - 5)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (80, 200, 80), 1)
    if finding is not None:
        box = finding.box
        cv2.rectangle(marked, (round(box.x), round(box.y)), (round(box.x + box.w), round(box.y + box.h)), (0, 140, 255), 2)
        cv2.drawMarker(marked, finding.survivor_px, (0, 140, 255), cv2.MARKER_CROSS, 18, 2)
        cv2.putText(marked, f"survivor ({finding.source})", (round(box.x), round(box.y + box.h + 16)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 140, 255), 1)
    return marked


def main(argv: Optional[Sequence[str]] = None, detector=None) -> int:
    parser = argparse.ArgumentParser(description="Find the survivor in a picture from the Blender twin.")
    parser.add_argument("--image", help="look at this picture instead of asking Blender (a view.json beside it is used if there)")
    parser.add_argument("--camera", choices=CAMERAS, default="rover")
    parser.add_argument("--model", default=str(DEFAULT_MODEL))
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--out", default=str(FRAMES_DIR / "survivor_check.png"), help="where to write the marked-up picture")
    args = parser.parse_args(argv)

    if args.image:
        image = cv2.imread(args.image)
        if image is None:
            print(f"Could not read the picture {args.image}", file=sys.stderr)
            return 2
        truth = load_truth(Path(args.image).with_suffix(".json"))
        picture_path = args.image
    else:
        picture_path = FRAMES_DIR / "rover_view.png"
        try:
            image, truth = request_snapshot(picture_path, args.camera, args.host, args.port)
        except TimeoutError as problem:
            print(problem, file=sys.stderr)
            return 2

    model_note = None
    if detector is None:
        try:
            detector = PersonDetector(args.model)
        except FileNotFoundError:
            model_note = "the person detector model is not downloaded, so only the simulation's box is available"
    model_boxes = detector.detect(image) if detector is not None else []

    finding = decide(model_boxes, truth)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), annotate(image, finding, model_boxes))
    box = finding.box if finding is not None else None
    print(json.dumps({
        "source": finding.source if finding else None,
        "model_found": len(model_boxes),
        "model_agrees": finding.model_agrees if finding else None,
        "survivor_px": list(finding.survivor_px) if finding else None,
        "box": {"x": box.x, "y": box.y, "w": box.w, "h": box.h} if box else None,
        "picture": str(picture_path),
        "annotated": str(out),
        "note": model_note,
    }))
    return 0 if finding else 1


if __name__ == "__main__":
    sys.exit(main())
