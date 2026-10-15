
"""Build and validate messages for the Still Here rover protocol."""

from __future__ import annotations

import json
from typing import Any, Iterable, Mapping


def _positive_plan_id(plan_id: Any) -> int:
    """A plan id is a positive whole number, like models.Plan.plan_id. The rover reads it as
    an integer, so a text id such as "run-001" would be refused as a bad plan."""
    if isinstance(plan_id, bool) or not isinstance(plan_id, int) or plan_id <= 0:
        raise ValueError(f"plan_id must be a positive whole number, got {plan_id!r}")
    return plan_id


def _validate_step(step: Mapping[str, Any]) -> dict[str, Any]:
    """Validate one pick/drop step using the shared protocol format."""
    required = {"id", "action", "x", "y", "z"}
    missing = required - step.keys()

    if missing:
        raise ValueError(f"Step is missing fields: {sorted(missing)}")

    step_id = step["id"]
    if isinstance(step_id, bool) or not isinstance(step_id, int) or step_id <= 0:
        raise ValueError("Step id must be a positive integer")

    action = step["action"]
    if action not in {"pick", "drop"}:
        raise ValueError("Step action must be 'pick' or 'drop'")

    validated = {"id": step_id, "action": action}

    for axis in ("x", "y", "z"):
        value = step[axis]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{axis} must be a number in millimetres")
        validated[axis] = value

    return validated


def build_plan_message(
    plan_id: int,
    steps: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build a plan message to store the approved plan on the rover."""
    valid_plan_id = _positive_plan_id(plan_id)
    valid_steps = [_validate_step(step) for step in steps]

    if not valid_steps:
        raise ValueError("A plan must contain at least one step")

    step_ids = [step["id"] for step in valid_steps]
    if len(step_ids) != len(set(step_ids)):
        raise ValueError("Step IDs must be unique")

    return {
        "type": "plan",
        "plan_id": valid_plan_id,
        "steps": valid_steps,
    }


def build_plan_start_message(plan_id: int) -> dict[str, Any]:
    """Build a message to start a plan already stored on the rover."""
    return {
        "type": "plan_start",
        "plan_id": _positive_plan_id(plan_id),
    }


def build_abort_message() -> dict[str, str]:
    """Build the protocol's safe-stop request."""
    return {"type": "abort"}


# Joint limits in degrees, the same as sim_rover.py. The firmware should refuse anything outside them.
# The elbow reaches 135 degrees each way (270 in all), confirmed by the team. A standard hobby servo turns only
# about 180 degrees, so that joint needs a servo or linkage that gives the larger range. The other joints'
# ranges are still the design's assumptions until the arm is measured.
ARM_LIMITS_DEG = {
    "base": (-90.0, 90.0),
    "shoulder": (0.0, 120.0),
    "elbow": (-135.0, 135.0),
    "gripper": (0.0, 90.0),  # 0 closed, 90 open
}


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value or abs(value) == float("inf"):
        raise ValueError(f"{name} must be a number, got {value!r}")
    return float(value)


def build_drive_message(left: float, right: float) -> dict[str, Any]:
    """Wheel speeds, each from -1 (full reverse) to 1 (full forward). Out-of-range is clamped."""
    clamp = lambda v: max(-1.0, min(1.0, v))  # noqa: E731
    return {"type": "drive", "left": clamp(_finite(left, "left")), "right": clamp(_finite(right, "right"))}


def build_arm_pose_message(
    base: float, shoulder: float, elbow: float, gripper: float, speed: float = 1.0
) -> dict[str, Any]:
    """Move the arm to a pose. Each joint is held inside its limits, and speed is 0.05 to 1."""
    pose = {"base": base, "shoulder": shoulder, "elbow": elbow, "gripper": gripper}
    out: dict[str, Any] = {"type": "arm_pose"}
    for joint, (low, high) in ARM_LIMITS_DEG.items():
        out[joint] = max(low, min(high, _finite(pose[joint], joint)))
    out["speed"] = max(0.05, min(1.0, _finite(speed, "speed")))
    return out


def encode_message(message: Mapping[str, Any]) -> str:
    """Encode a message as one JSON text message for the rover link."""
    if not isinstance(message, Mapping) or not isinstance(
        message.get("type"), str
    ):
        raise ValueError("Message must be an object with a string 'type'")

    return json.dumps(message, separators=(",", ":"), allow_nan=False)


if __name__ == "__main__":
    # Local demonstration only; this does not move a physical rover.
    demo_steps = [
        {"id": 1, "action": "pick", "x": 100, "y": 20, "z": 40},
        {"id": 2, "action": "drop", "x": 180, "y": 20, "z": 40},
    ]

    plan = build_plan_message(1, demo_steps)
    start = build_plan_start_message(1)

    print("Plan message:")
    print(encode_message(plan))

    print("\nPlan-start message:")
    print(encode_message(start))
