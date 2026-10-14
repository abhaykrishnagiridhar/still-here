"""Turns phone tilt into rover messages (docs/protocol.md). No network, no clock, easy to test.

Hold the phone flat, screen up, like a game controller.
  Drive mode: tilt forward/back = throttle, tilt left/right = steer.
  Arm mode:   tilt left/right = swing the base, tilt forward/back = shoulder down/up.
              The elbow slider and the gripper button come from the phone screen.

Only beta (front-back) and gamma (left-right) are used. alpha (compass heading) drifts on most
phones, so it is deliberately ignored.
"""

from typing import Optional

TILT_FULL_DEG = 30.0  # tilt that gives full output
DEADZONE_DEG = 4.0  # ignore tiny wobble around the calibrated centre
SMOOTHING = 0.35  # 0..1, higher follows the phone faster
STALE_AFTER_S = 0.5  # no phone data for this long means stop the wheels

SHOULDER_CENTRE_DEG = 60.0
SHOULDER_SWING_DEG = 60.0
BASE_SWING_DEG = 90.0
ELBOW_LIMIT_DEG = 135.0
GRIPPER_OPEN_DEG = 90.0
GRIPPER_CLOSED_DEG = 0.0


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def axis(delta_deg: float) -> float:
    """Tilt away from centre as -1..1, with a dead zone so a resting hand does nothing."""
    if abs(delta_deg) <= DEADZONE_DEG:
        return 0.0
    sign = 1.0 if delta_deg > 0 else -1.0
    span = TILT_FULL_DEG - DEADZONE_DEG
    return sign * clamp((abs(delta_deg) - DEADZONE_DEG) / span, 0.0, 1.0)


def drive_command(d_beta: float, d_gamma: float) -> tuple[float, float]:
    """(left, right) wheel speeds from tilt away from centre. Top edge down = forward."""
    throttle = -axis(d_beta)
    steer = axis(d_gamma)  # right edge down = turn right
    left, right = throttle + steer, throttle - steer
    biggest = max(abs(left), abs(right), 1.0)
    return (left / biggest, right / biggest)


def arm_command(d_beta: float, d_gamma: float, elbow: float, grip_open: bool) -> dict:
    return {
        "base": -axis(d_gamma) * BASE_SWING_DEG,
        "shoulder": SHOULDER_CENTRE_DEG + axis(d_beta) * SHOULDER_SWING_DEG,
        "elbow": clamp(elbow, -ELBOW_LIMIT_DEG, ELBOW_LIMIT_DEG),
        "gripper": GRIPPER_OPEN_DEG if grip_open else GRIPPER_CLOSED_DEG,
    }


class GyroSession:
    """One phone. Remembers the calibrated centre, smooths the tilt and builds messages."""

    def __init__(self) -> None:
        self._ref = (0.0, 0.0)
        self._smooth: Optional[tuple[float, float]] = None
        self._mode = "drive"
        self._last_sample_t: Optional[float] = None
        self._stopped = True

    def calibrate(self, beta: float, gamma: float) -> None:
        """Use the current hold as the centre. Call when the phone is held how you like."""
        self._ref = (beta, gamma)
        self._smooth = (beta, gamma)

    def update(self, sample: dict, now: float) -> list[dict]:
        try:
            beta = float(sample["beta"])
            gamma = float(sample["gamma"])
        except (KeyError, TypeError, ValueError):
            return []
        if self._smooth is None or sample.get("calibrate"):
            self.calibrate(beta, gamma)  # first sample: whatever you hold is the centre

        sb, sg = self._smooth
        self._smooth = (sb + SMOOTHING * (beta - sb), sg + SMOOTHING * (gamma - sg))
        d_beta, d_gamma = self._smooth[0] - self._ref[0], self._smooth[1] - self._ref[1]
        self._last_sample_t = now

        if sample.get("stop"):
            self._stopped = True
            return [{"type": "drive", "left": 0.0, "right": 0.0}]
        self._stopped = False

        mode = sample.get("mode", self._mode)
        mode = mode if mode in ("drive", "arm") else self._mode
        out: list[dict] = []
        if mode != self._mode:
            self._mode = mode
            out.append({"type": "drive", "left": 0.0, "right": 0.0})  # never carry speed across modes
        if mode == "drive":
            left, right = drive_command(d_beta, d_gamma)
            out.append({"type": "drive", "left": round(left, 3), "right": round(right, 3)})
        else:
            pose = arm_command(d_beta, d_gamma, float(sample.get("elbow", -90.0)), bool(sample.get("grip", True)))
            out.append({"type": "arm_pose", **{k: round(v, 2) for k, v in pose.items()}, "speed": 1.0})
        return out

    def idle(self, now: float) -> list[dict]:
        """Call regularly. Stops the wheels once if the phone went quiet (screen locked, Wi-Fi gone)."""
        if self._stopped or self._last_sample_t is None:
            return []
        if now - self._last_sample_t < STALE_AFTER_S:
            return []
        self._stopped = True
        return [{"type": "drive", "left": 0.0, "right": 0.0}]
