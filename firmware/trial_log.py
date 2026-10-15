
import csv
import math
from datetime import datetime


def log_trial(
    target_x, target_y, actual_x, actual_y,
    target_angle, actual_angle
):
    position_error = math.hypot(
        actual_x - target_x,
        actual_y - target_y
    )

    angle_error = abs(
        (actual_angle - target_angle + 180) % 360 - 180
    )

    passed = position_error <= 5 and angle_error <= 10

    result = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "position_error_mm": round(position_error, 3),
        "angle_error_deg": round(angle_error, 3),
        "position_pass": position_error <= 5,
        "angle_pass": angle_error <= 10,
        "overall_pass": passed
    }

    with open("trials.csv", "a", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=result.keys())

        if file.tell() == 0:
            writer.writeheader()

        writer.writerow(result)

    print(result)
    print("RESULT:", "PASS" if passed else "FAIL")


if __name__ == "__main__":
    # Example test values; replace with measured results.
    log_trial(
        target_x=100,
        target_y=50,
        actual_x=103,
        actual_y=52,
        target_angle=90,
        actual_angle=96
    )
