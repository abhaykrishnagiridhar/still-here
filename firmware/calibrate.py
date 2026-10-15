
import json
import numpy as np


def calibrate(points):
    # Each point: [pixel_x, pixel_y, real_x_mm, real_y_mm]
    if len(points) < 3:
        raise ValueError("Provide at least 3 calibration points")

    points = np.array(points, dtype=float)

    A = np.column_stack((
        points[:, 0],
        points[:, 1],
        np.ones(len(points))
    ))

    if np.linalg.matrix_rank(A) < 3:
        raise ValueError("Calibration points must not be collinear")

    target = points[:, 2:4]
    coefficients, *_ = np.linalg.lstsq(A, target, rcond=None)

    predicted = A @ coefficients
    errors = np.linalg.norm(predicted - target, axis=1)

    result = {
        "coefficients": coefficients.tolist(),
        "mean_error_mm": float(np.mean(errors)),
        "max_error_mm": float(np.max(errors))
    }

    with open("calibration.json", "w") as file:
        json.dump(result, file, indent=2)

    print(json.dumps(result, indent=2))


def pixel_to_mm(pixel_x, pixel_y):
    with open("calibration.json") as file:
        model = json.load(file)

    coefficients = np.array(model["coefficients"])
    xy = np.array([pixel_x, pixel_y, 1]) @ coefficients

    return float(xy[0]), float(xy[1])


if __name__ == "__main__":
    # REPLACE these example values with measured points.
    points = [
        [100, 100, 0, 0],
        [300, 100, 50, 0],
        [100, 300, 0, 50],
        [300, 300, 50, 50],
        [200, 200, 25, 25]
    ]

    calibrate(points)
    print("Example mapped point:", pixel_to_mm(200, 200))
