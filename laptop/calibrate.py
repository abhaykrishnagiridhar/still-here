"""Calibration: where a point in the camera picture is on the table, in millimetres.

Put the rover where it will start, mark at least 4 spots on the table that are not in one line
(more is better, spread over the whole area the blocks can be in), and measure each one from the
rover: how far forward and how far to the left, in millimetres. Note the pixel where each mark
shows in the picture. Save them as a list of [pixel_x, pixel_y, forward_mm, left_mm]:

    [[320, 480, 0, 0], [320, 280, 50, 0], [120, 480, 0, 50], [520, 480, 0, -50]]

then run:   python calibrate.py points.json

The fit is a homography (a perspective mapping), which is right for a camera that looks down at
the table at an angle. A flat scale (scale.py) is only right for a camera looking straight down.
The camera must not move after calibrating. If it does, calibrate again.
"""

import argparse
import json
import sys
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from typing import Optional, Sequence

import cv2
import numpy as np

LAPTOP_DIR = Path(__file__).resolve().parent
DEFAULT_FILE = LAPTOP_DIR / "calibration.json"  # the team's own measurement, git-ignored

MIN_POINTS = 4
MAX_ERROR_MM = 5.0  # a fit worse than the 5 mm test tolerance is not good enough to plan with
_DEGENERATE = 1e-9

Point = tuple[float, float]


@dataclass(frozen=True)
class Calibration:
    """A mapping between picture pixels and (forward, left) millimetres from the rover."""

    matrix: tuple[tuple[float, float, float], ...]  # pixels to millimetres
    mean_error_mm: float
    max_error_mm: float

    @staticmethod
    def _map(matrix: np.ndarray, point: Point) -> Point:
        x, y, w = matrix @ np.array([point[0], point[1], 1.0])
        return (float(x / w), float(y / w))

    def to_mm(self, point_px: Point) -> Point:
        """(forward, left) in millimetres from the rover, for a point in the picture."""
        return self._map(np.array(self.matrix), point_px)

    def to_px(self, point_mm: Point) -> Point:
        """The picture position of a (forward, left) point. The inverse of to_mm."""
        return self._map(np.linalg.inv(np.array(self.matrix)), point_mm)

    def radius_px(self, centre_mm: Point, radius_mm: float) -> float:
        """How many pixels a circle of this radius, centred there on the table, is wide."""
        centre = np.array(self.to_px(centre_mm))
        spread = [
            np.linalg.norm(np.array(self.to_px((centre_mm[0] + dx, centre_mm[1] + dy))) - centre)
            for dx, dy in ((radius_mm, 0), (-radius_mm, 0), (0, radius_mm), (0, -radius_mm))
        ]
        return float(np.mean(spread))


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)


def _on_one_line(points: np.ndarray) -> bool:
    centred = points - points.mean(axis=0)
    singular = np.linalg.svd(centred, compute_uv=False)
    return singular[0] < _DEGENERATE or singular[-1] < 1e-6 * singular[0]


def fit(points: Sequence[Sequence[float]]) -> Calibration:
    """Fit the mapping to measured points, each [pixel_x, pixel_y, forward_mm, left_mm]."""
    if not isinstance(points, (list, tuple)):
        raise ValueError("points must be a list of [pixel_x, pixel_y, forward_mm, left_mm]")
    if len(points) < MIN_POINTS:
        raise ValueError(f"Calibration needs at least {MIN_POINTS} points, got {len(points)}")
    for row in points:
        if not isinstance(row, (list, tuple)) or len(row) != 4 or not all(_is_number(v) for v in row):
            raise ValueError(f"Each point must be 4 numbers [pixel_x, pixel_y, forward_mm, left_mm], got {row!r}")
    data = np.array(points, dtype=float)
    pixels, millimetres = data[:, :2], data[:, 2:]
    if _on_one_line(pixels) or _on_one_line(millimetres):
        raise ValueError("The calibration points all lie on one line. Spread them over the table.")
    matrix, _ = cv2.findHomography(pixels, millimetres, 0)
    if matrix is None or not np.all(np.isfinite(matrix)) or abs(np.linalg.det(matrix)) < _DEGENERATE:
        raise ValueError("Could not fit a calibration to these points. Check the measurements.")
    matrix = matrix / matrix[2, 2] if abs(matrix[2, 2]) > _DEGENERATE else matrix
    predicted = cv2.perspectiveTransform(pixels.reshape(-1, 1, 2), matrix).reshape(-1, 2)
    errors = np.linalg.norm(predicted - millimetres, axis=1)
    return Calibration(
        matrix=tuple(tuple(float(v) for v in row) for row in matrix),
        mean_error_mm=float(errors.mean()),
        max_error_mm=float(errors.max()),
    )


def save(calibration: Calibration, path: Path = DEFAULT_FILE) -> None:
    body = {
        "matrix": [list(row) for row in calibration.matrix],
        "mean_error_mm": calibration.mean_error_mm,
        "max_error_mm": calibration.max_error_mm,
    }
    Path(path).write_text(json.dumps(body, indent=2), encoding="utf-8")


def load(path: Path = DEFAULT_FILE) -> Calibration:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"{path} not found. Make it with: python calibrate.py points.json")
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
        rows = body["matrix"]
        matrix = np.array(rows, dtype=float)
        if matrix.shape != (3, 3) or not np.all(np.isfinite(matrix)) or abs(np.linalg.det(matrix)) < _DEGENERATE:
            raise ValueError("matrix must be a usable 3 by 3 table of numbers")
        return Calibration(
            matrix=tuple(tuple(float(v) for v in row) for row in rows),
            mean_error_mm=float(body["mean_error_mm"]),
            max_error_mm=float(body["max_error_mm"]),
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        raise ValueError(f"{path.name} is not a calibration file made by calibrate.py: {error!r}") from error


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Fit the camera calibration to measured points")
    parser.add_argument("points", help="JSON file: a list of [pixel_x, pixel_y, forward_mm, left_mm]")
    parser.add_argument("--out", default=str(DEFAULT_FILE), help="where to save the calibration")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    try:
        points = json.loads(Path(args.points).read_text(encoding="utf-8"))
        calibration = fit(points)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        print(f"Could not calibrate from {args.points}: {error}", file=sys.stderr)
        return 1
    save(calibration, Path(args.out))
    print(f"Saved {args.out}")
    print(f"Mean error {calibration.mean_error_mm:.2f} mm, max error {calibration.max_error_mm:.2f} mm")
    if calibration.max_error_mm > MAX_ERROR_MM:
        print(f"WARNING: the worst point is more than {MAX_ERROR_MM:g} mm out. Re-measure the marks.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
