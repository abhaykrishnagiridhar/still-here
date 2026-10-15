
"""Still Here - scan, plan, approve, execute, and verify, in the console.

This walks through the same protocol sequence as the operator page (server.py) without a
browser or a camera, against a rover link you supply. The mock link is for local testing only.
"""

from dataclasses import dataclass
from typing import Any, Callable

from plan_message import (
    build_plan_message,
    build_plan_start_message,
    build_abort_message,
)
from report import build_report, choose_summary, write_report


@dataclass
class RunResult:
    status: str
    plan_id: int | None
    attempts: int
    message: str
    verification: dict[str, Any] | None = None


class RoverLink:
    """Interface to replace with the real rover connection later."""

    def scan(self) -> dict[str, Any]:
        raise NotImplementedError

    def send(self, message: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def verify(self, plan: dict[str, Any]) -> dict[str, Any]:
        """Check the result. Must return "verified" (bool) and, as measured by the rover or the
        camera, "steps_completed" and "obstacles_detected" (whole numbers)."""
        raise NotImplementedError


def create_plan(scan_data: dict[str, Any], plan_id: int) -> dict[str, Any]:
    """Create a protocol plan from scan results."""
    steps = scan_data.get("steps", [])
    return build_plan_message(plan_id, steps)


def run_controller(
    rover: RoverLink,
    approve: Callable[[dict[str, Any]], bool],
    max_attempts: int = 3,
) -> RunResult:
    for attempt in range(1, max_attempts + 1):
        print(f"\n--- Attempt {attempt}/{max_attempts} ---")
        print("Scanning environment...")
        scan_data = rover.scan()

        print("Creating plan...")
        plan_id = attempt  # a whole number, as the rover protocol expects
        plan = create_plan(scan_data, plan_id)

        print("Waiting for operator approval...")
        print("\nProposed plan:")
        for step in plan["steps"]:
            print(
                f"  Step {step['id']}: {step['action']} at "
                f"x={step['x']}, y={step['y']}, z={step['z']} mm"
            )

        if not approve(plan):
            rover.send(build_abort_message())
            return RunResult(
                "aborted", plan_id, attempt,
                "Operator did not approve the plan.",
                {"verified": False},
            )

        print("Sending plan to rover...")
        response = rover.send(plan)
        if not response.get("accepted", False):
            print("Rover rejected the plan.")
            continue

        print("Starting approved plan...")
        response = rover.send(build_plan_start_message(plan_id))
        if not response.get("started", False):
            print("Rover did not start the plan.")
            continue

        print("Verifying result...")
        verification = rover.verify(plan)
        if verification.get("verified", False):
            print("Verification passed. Run finished.")
            return RunResult(
                "completed", plan_id, attempt,
                "Plan executed and verified.", verification,
            )

        print("Verification failed; trying again.")

    rover.send(build_abort_message())
    return RunResult(
        "failed", None, max_attempts,
        "Could not verify the plan after repeated attempts.",
        {"verified": False},
    )


class MockRoverLink(RoverLink):
    """Simulates a rover for local software testing only."""

    def __init__(self):
        self.last_plan = None
        self.started = False
        self.aborted = False

    def scan(self) -> dict[str, Any]:
        print("[MockRover] Scan complete.")
        return {
            "steps": [
                {"id": 1, "action": "pick", "x": 100, "y": 20, "z": 40},
                {"id": 2, "action": "drop", "x": 180, "y": 20, "z": 40},
            ]
        }

    def send(self, message: dict[str, Any]) -> dict[str, Any]:
        print(f"[MockRover] Received: {message}")

        if message.get("type") == "plan":
            self.last_plan = message
            return {"accepted": True}

        if message.get("type") == "plan_start":
            self.started = True
            return {"started": True}

        if message.get("type") == "abort":
            self.aborted = True
            return {"aborted": True}

        return {"accepted": False}

    def verify(self, plan: dict[str, Any]) -> dict[str, Any]:
        verified = self.started and not self.aborted
        planned = len(plan["steps"])
        return {
            "verified": verified,
            "steps_completed": planned if verified else 0,
            "obstacles_detected": 0,
            "observed": "mock execution completed" if verified else "not verified",
        }


def console_approval(plan: dict[str, Any]) -> bool:
    answer = input("Approve this plan? (yes/no): ").strip().lower()
    return answer in {"yes", "y"}


def build_facts(result: RunResult, planned_steps: int, aborted: bool) -> dict[str, Any]:
    """The facts for the report, taken from what the rover reported, never assumed."""
    verification = result.verification or {}
    verified = verification.get("verified", False) is True
    return {
        "run_id": f"stillhere-run-{result.plan_id}" if result.plan_id else "stillhere-run-unknown",
        "status": result.status,
        "verified": verified,
        "steps_completed": int(verification.get("steps_completed", 0)),
        "steps_planned": planned_steps,
        "obstacles_detected": int(verification.get("obstacles_detected", 0)),
        "safe_stop_triggered": aborted or result.status == "aborted",
    }


def summary_for(facts: dict[str, Any]) -> str | None:
    return choose_summary(build_report(facts))


if __name__ == "__main__":
    rover = MockRoverLink()
    result = run_controller(rover, console_approval)

    print("\n--- Run result ---")
    print(f"Status: {result.status}")
    print(f"Plan ID: {result.plan_id}")
    print(f"Attempts: {result.attempts}")
    print(f"Message: {result.message}")
    print(f"Verification: {result.verification}")

    planned_steps = len(rover.last_plan["steps"]) if rover.last_plan else 0
    facts = build_facts(result, planned_steps, rover.aborted)
    write_report(facts, "safe_path_report.json", summary_for(facts))
