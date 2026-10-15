
"""Build and validate messages for the Still Here rover protocol."""

from __future__ import annotations

import json
from typing import Any, Iterable, Mapping


def _positive_plan_id(plan_id: Any) -> str | int:
    """Accept a non-empty string or positive integer as a plan ID."""
    if isinstance(plan_id, bool):
        raise ValueError("plan_id must not be a boolean")

    if isinstance(plan_id, int):
        if plan_id <= 0:
            raise ValueError("Integer plan_id must be positive")
        return plan_id

    if isinstance(plan_id, str) and plan_id.strip():
        return plan_id.strip()

    raise ValueError("plan_id must be a positive integer or non-empty string")


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
    plan_id: str | int,
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


def build_plan_start_message(plan_id: str | int) -> dict[str, Any]:
    """Build a message to start a plan already stored on the rover."""
    return {
        "type": "plan_start",
        "plan_id": _positive_plan_id(plan_id),
    }


def build_abort_message() -> dict[str, str]:
    """Build the protocol's safe-stop request."""
    return {"type": "abort"}


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

    plan = build_plan_message("demo-001", demo_steps)
    start = build_plan_start_message("demo-001")

    print("Plan message:")
    print(encode_message(plan))

    print("\nPlan-start message:")
    print(encode_message(start))
