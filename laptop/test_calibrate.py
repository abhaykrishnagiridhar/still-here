"""Calibration: where a point in the camera picture is on the table, in millimetres."""

import json

import numpy as np
import pytest

import calibrate
from calibrate import Calibration, fit, load, main, save

# A flat, level camera: 0.25 mm per pixel, the rover at pixel (320, 480). Points are
# [pixel_x, pixel_y, forward_mm, left_mm].
LEVEL = [
    [320, 480, 0, 0],
    [320, 280, 50, 0],
    [120, 480, 0, 50],
    [520, 480, 0, -50],
    [220, 380, 25, 25],
]

# A tilted camera: a true perspective mapping, so far points are squeezed together.
TILT = np.array([[0.3, 0.02, -90.0], [0.01, -0.45, 210.0], [0.0001, 0.0012, 1.0]])


def tilted_points(pixels):
    rows = []
    for x, y in pixels:
        u, v, w = TILT @ np.array([x, y, 1.0])
        rows.append([x, y, u / w, v / w])
    return rows


TILT_PIXELS = [(100, 400), (540, 410), (150, 200), (500, 190), (320, 300), (320, 120)]


def test_a_level_camera_gives_a_quarter_millimetre_per_pixel():
    cal = fit(LEVEL)

    forward, left = cal.to_mm((320, 280))

    assert (forward, left) == pytest.approx((50, 0), abs=1e-6)
    assert cal.mean_error_mm < 1e-6 and cal.max_error_mm < 1e-6


def test_a_tilted_camera_is_fitted_exactly_by_a_perspective_model():
    cal = fit(tilted_points(TILT_PIXELS))

    assert cal.max_error_mm < 1e-4
    for x, y in [(250, 330), (450, 250)]:
        u, v, w = TILT @ np.array([x, y, 1.0])
        assert cal.to_mm((x, y)) == pytest.approx((u / w, v / w), abs=1e-4)


def test_one_pixel_is_more_table_far_away_than_close_up_on_a_tilted_camera():
    cal = fit(tilted_points(TILT_PIXELS))
    near = abs(cal.to_mm((320, 401))[0] - cal.to_mm((320, 400))[0])
    far = abs(cal.to_mm((320, 141))[0] - cal.to_mm((320, 140))[0])

    assert far > 1.4 * near  # this camera squeezes the far table about 1.6 times


def test_millimetres_back_to_pixels_is_the_inverse():
    cal = fit(tilted_points(TILT_PIXELS))

    for pixel in [(100, 400), (320, 300), (500, 190)]:
        assert cal.to_px(cal.to_mm(pixel)) == pytest.approx(pixel, abs=1e-4)


def test_a_circle_radius_in_millimetres_is_drawn_in_pixels_at_that_place():
    cal = fit(LEVEL)

    assert cal.radius_px((25, 0), 100) == pytest.approx(400, rel=1e-6)


def test_noisy_measurements_report_how_far_off_they_are():
    noisy = [row[:] for row in LEVEL]
    noisy[4][2] += 4  # one point was measured 4 mm out

    cal = fit(noisy)

    assert 0.5 < cal.max_error_mm < 4
    assert cal.mean_error_mm <= cal.max_error_mm


@pytest.mark.parametrize("count", [0, 1, 3])
def test_too_few_points_are_refused(count):
    with pytest.raises(ValueError, match="at least 4"):
        fit(LEVEL[:count])


def test_points_on_one_line_are_refused():
    line = [[100 + 50 * i, 300, 10 * i, 0] for i in range(5)]

    with pytest.raises(ValueError, match="one line"):
        fit(line)


@pytest.mark.parametrize(
    "bad",
    [
        LEVEL[:4] + [[1, 2, 3]],
        LEVEL[:4] + [[1, 2, 3, "x"]],
        LEVEL[:4] + [[1, 2, 3, float("nan")]],
        "points",
        None,
        5,
    ],
)
def test_points_that_are_not_four_numbers_each_are_refused(bad):
    with pytest.raises(ValueError):
        fit(bad)


def test_a_saved_calibration_loads_back_the_same(tmp_path):
    cal = fit(tilted_points(TILT_PIXELS))
    path = tmp_path / "calibration.json"

    save(cal, path)
    again = load(path)

    assert again.to_mm((250, 330)) == pytest.approx(cal.to_mm((250, 330)), abs=1e-9)
    assert set(json.loads(path.read_text())) == {"matrix", "mean_error_mm", "max_error_mm"}


def test_a_missing_calibration_file_says_so(tmp_path):
    with pytest.raises(FileNotFoundError, match="calibrate.py"):
        load(tmp_path / "nope.json")


@pytest.mark.parametrize(
    "text",
    ["not json", "[]", '{"matrix": [[1, 2], [3, 4]]}', '{"matrix": "x"}', '{"matrix": [[0,0,0],[0,0,0],[0,0,0]]}'],
)
def test_a_broken_calibration_file_is_refused_with_its_name(tmp_path, text):
    path = tmp_path / "calibration.json"
    path.write_text(text, encoding="utf-8")

    with pytest.raises(ValueError, match="calibration.json"):
        load(path)


def test_the_old_example_file_format_is_not_mistaken_for_a_real_calibration(tmp_path):
    old = {"coefficients": [[0.25, 0], [0, 0.25], [-25, -25]], "mean_error_mm": 0, "max_error_mm": 0}
    path = tmp_path / "calibration.json"
    path.write_text(json.dumps(old), encoding="utf-8")

    with pytest.raises(ValueError, match="matrix"):
        load(path)


# --- the command line ---------------------------------------------------------------------


def test_the_command_fits_a_points_file_and_writes_the_calibration(tmp_path, capsys):
    points = tmp_path / "points.json"
    points.write_text(json.dumps(LEVEL), encoding="utf-8")
    out = tmp_path / "calibration.json"

    code = main([str(points), "--out", str(out)])

    assert code == 0
    assert isinstance(load(out), Calibration)
    assert "max error" in capsys.readouterr().out.lower()


def test_the_command_warns_when_the_fit_is_worse_than_the_test_allows(tmp_path, capsys):
    noisy = [row[:] for row in LEVEL]
    noisy[4][2] += 40
    points = tmp_path / "points.json"
    points.write_text(json.dumps(noisy), encoding="utf-8")

    code = main([str(points), "--out", str(tmp_path / "c.json")])

    assert code == 0
    assert "warning" in capsys.readouterr().out.lower()


def test_the_command_reports_a_bad_points_file_and_writes_nothing(tmp_path, capsys):
    points = tmp_path / "points.json"
    points.write_text(json.dumps(LEVEL[:2]), encoding="utf-8")
    out = tmp_path / "calibration.json"

    code = main([str(points), "--out", str(out)])

    assert code == 1
    assert not out.exists()
    assert "at least 4" in capsys.readouterr().err


def test_the_command_reports_a_missing_points_file(tmp_path, capsys):
    assert main([str(tmp_path / "none.json")]) == 1
    assert "none.json" in capsys.readouterr().err


def test_the_default_calibration_file_is_next_to_the_code():
    assert calibrate.DEFAULT_FILE.name == "calibration.json"
    assert calibrate.DEFAULT_FILE.parent == calibrate.LAPTOP_DIR
