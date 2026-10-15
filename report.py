
"""Still Here - fact-first safe-path reporting."""

from dataclasses import dataclass, asdict
from typing import Any
import json


@dataclass
class SafePathReport:
    run_id: str
    status: str
    verified: bool
    steps_completed: int
    steps_planned: int
    obstacles_detected: int
    safe_stop_triggered: bool
    summary: str | None = None


def build_report(facts: dict[str, Any]) -> SafePathReport:
    """Build a report from recorded facts, not assumptions."""

    required = {
        "run_id",
        "status",
        "verified",
        "steps_completed",
        "steps_planned",
        "obstacles_detected",
        "safe_stop_triggered",
    }

    missing = required - facts.keys()
    if missing:
        raise ValueError(f"Missing report facts: {sorted(missing)}")

    if not isinstance(facts["verified"], bool):
        raise ValueError("'verified' must be true or false")

    if not isinstance(facts["safe_stop_triggered"], bool):
        raise ValueError("'safe_stop_triggered' must be true or false")

    for field in (
        "steps_completed",
        "steps_planned",
        "obstacles_detected",
    ):
        value = facts[field]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{field} must be a non-negative integer")

    if facts["steps_completed"] > facts["steps_planned"]:
        raise ValueError("Completed steps cannot exceed planned steps")

    if not isinstance(facts["run_id"], str) or not facts["run_id"].strip():
        raise ValueError("run_id must be a non-empty string")

    if not isinstance(facts["status"], str) or not facts["status"].strip():
        raise ValueError("status must be a non-empty string")

    return SafePathReport(
        run_id=facts["run_id"],
        status=facts["status"],
        verified=facts["verified"],
        steps_completed=facts["steps_completed"],
        steps_planned=facts["steps_planned"],
        obstacles_detected=facts["obstacles_detected"],
        safe_stop_triggered=facts["safe_stop_triggered"],
    )


def check_summary(report: SafePathReport, summary: str) -> bool:
    """Allow only a summary that does not contradict recorded facts.

    To avoid unsupported claims, this intentionally accepts only
    a small set of predefined summaries.
    """
    allowed = {
        "Run completed and verified.":
            report.status == "completed"
            and report.verified
            and report.steps_completed == report.steps_planned
            and not report.safe_stop_triggered,

        "Run was not verified.":
            not report.verified,

        "Run stopped for safety.":
            report.safe_stop_triggered,
    }

    return allowed.get(summary, False)


def render_report(
    report: SafePathReport,
    summary: str | None = None,
) -> str:
    """Render facts first; include a validated summary if provided."""

    output = [
        "STILL HERE - SAFE-PATH REPORT",
        f"Run ID: {report.run_id}",
        f"Status: {report.status}",
        f"Verified: {report.verified}",
        f"Steps completed: {report.steps_completed}",
        f"Steps planned: {report.steps_planned}",
        f"Obstacles detected: {report.obstacles_detected}",
        f"Safe stop triggered: {report.safe_stop_triggered}",
    ]

    if summary is not None:
        if check_summary(report, summary):
            output.extend(["", f"Summary: {summary}"])
        else:
            output.extend([
                "",
                "Summary omitted: it is unsupported or conflicts with facts.",
            ])

    return "\n".join(output)


def play_completion_chime() -> None:
    """Play one short completion chime when supported by the OS."""
    try:
        import winsound
        winsound.MessageBeep(winsound.MB_OK)
    except (ImportError, RuntimeError):
        # Keep reporting usable on systems without winsound.
        print("[Completion chime unavailable on this system]")


def write_report(
    facts: dict[str, Any],
    output_path: str = "safe_path_report.json",
    summary: str | None = None,
) -> SafePathReport:
    """Validate facts, save a JSON report, and chime once."""

    report = build_report(facts)

    if summary is not None and not check_summary(report, summary):
        print("Note: optional summary rejected because it is not supported by facts.")

    report_data = asdict(report)
    if summary is not None and check_summary(report, summary):
        report_data["summary"] = summary

    with open(output_path, "w", encoding="utf-8") as file:
        json.dump(report_data, file, indent=2)

    print(render_report(report, summary))

    # Exactly one chime per successful write_report call.
    play_completion_chime()
    return report


if __name__ == "__main__":
    # Example data for local testing only.
    # Replace these values with facts returned by the actual rover.
    demo_facts = {
        "run_id": "stillhere-run-001",
        "status": "completed",
        "verified": True,
        "steps_completed": 2,
        "steps_planned": 2,
        "obstacles_detected": 0,
        "safe_stop_triggered": False,
    }

    write_report(
        demo_facts,
        output_path="safe_path_report.json",
        summary="Run completed and verified.",
    )
