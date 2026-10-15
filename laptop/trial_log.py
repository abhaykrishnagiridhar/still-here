"""The two-block stack test log. Run the test 10 times, log each run, and at least 8 must pass.

A run passes when the camera found both blocks, the top block was removed, and the bottom
block moved LESS than 5 mm and turned LESS than 10 degrees (the limits are in config.toml).
Measure the bottom block's position and angle before and after the run, then:

    python trial_log.py add --top-found yes --bottom-found yes --top-removed yes \\
        --before-x 100 --before-y 50 --before-deg 90 --after-x 103 --after-y 52 --after-deg 96
    python trial_log.py summary

Runs go into docs/trials.csv. Only the latest 10 count, so after a fix you can run 10 more.
"""

import argparse
import csv
import sys
from datetime import date
from math import hypot
from pathlib import Path
from typing import Optional, Sequence

from aruco import load_config

LAPTOP_DIR = Path(__file__).resolve().parent
TRIALS_FILE = LAPTOP_DIR.parent / "docs" / "trials.csv"
FIELDS = [
    "trial", "date", "top_found", "bottom_found", "top_removed",
    "bottom_shift_mm", "bottom_rotation_deg", "pass", "failure_cause", "notes",
]
GATE_PASSES = 8
GATE_TRIALS = 10
ADVICE = "Fix grip padding, block weight and camera placement, in that order, before any other feature."


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def angle_difference(before_deg: float, after_deg: float) -> float:
    """How far apart two angles are, the short way round (0 to 180 degrees)."""
    return abs((after_deg - before_deg + 180.0) % 360.0 - 180.0)


def read_trials(path: Path = TRIALS_FILE) -> list[dict]:
    path = Path(path)
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def _failures(top_found, bottom_found, top_removed, shift, turn, max_shift_mm, max_rotation_deg):
    if not top_found:
        return ["top block not found"]
    if not bottom_found:
        return ["bottom block not found"]
    if not top_removed:
        return ["top block not removed"]
    if shift is None or turn is None:
        return ["bottom block not measured, so it cannot be shown to be undisturbed"]
    causes = []
    if shift >= max_shift_mm:
        causes.append(f"bottom block moved {shift:.1f} mm (limit {max_shift_mm:g})")
    if turn >= max_rotation_deg:
        causes.append(f"bottom block rotated {turn:.1f} degrees (limit {max_rotation_deg:g})")
    return causes


def log_trial(
    path: Path,
    *,
    top_found: bool,
    bottom_found: bool,
    top_removed: bool,
    before_xy: Optional[tuple[float, float]] = None,
    after_xy: Optional[tuple[float, float]] = None,
    before_deg: Optional[float] = None,
    after_deg: Optional[float] = None,
    notes: str = "",
    max_shift_mm: float = 5.0,
    max_rotation_deg: float = 10.0,
    today: Optional[str] = None,
) -> dict:
    """Judge one run against the limits, add it to the log, and return the row."""
    measured = None not in (before_xy, after_xy, before_deg, after_deg) and bottom_found
    shift = hypot(after_xy[0] - before_xy[0], after_xy[1] - before_xy[1]) if measured else None
    turn = angle_difference(before_deg, after_deg) if measured else None
    causes = _failures(top_found, bottom_found, top_removed, shift, turn, max_shift_mm, max_rotation_deg)

    path = Path(path)
    existing = read_trials(path)
    row = {
        "trial": str(len(existing) + 1),
        "date": today or date.today().isoformat(),
        "top_found": _yes_no(top_found),
        "bottom_found": _yes_no(bottom_found),
        "top_removed": _yes_no(top_removed),
        "bottom_shift_mm": "" if shift is None else f"{shift:.1f}",
        "bottom_rotation_deg": "" if turn is None else f"{turn:.1f}",
        "pass": _yes_no(not causes),
        "failure_cause": "; ".join(causes),
        "notes": notes,
    }
    needs_header = not path.exists() or path.stat().st_size == 0
    with open(path, "a", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS)
        if needs_header:
            writer.writeheader()
        writer.writerow(row)
    return row


def summary(path: Path = TRIALS_FILE) -> dict:
    """How the latest 10 runs went against the gate."""
    trials = read_trials(path)
    latest = trials[-GATE_TRIALS:]
    passes = sum(1 for row in latest if row["pass"] == "yes")
    return {
        "trials": len(trials),
        "passes": passes,
        "counted": len(latest),
        "needed": GATE_PASSES,
        "of": GATE_TRIALS,
        "met": len(latest) == GATE_TRIALS and passes >= GATE_PASSES,
    }


def format_summary(result: dict) -> str:
    line = f"{result['passes']} of the last {result['counted']} trials passed (need {result['needed']} of {result['of']})."
    if result["met"]:
        return f"{line} Gate met."
    if result["counted"] < result["of"]:
        return f"{line} Gate not met yet: run {result['of'] - result['counted']} more."
    return f"{line} Gate not met. {ADVICE}"


def _yes_no_arg(text: str) -> bool:
    if text.lower() in ("yes", "y", "true", "1"):
        return True
    if text.lower() in ("no", "n", "false", "0"):
        return False
    raise argparse.ArgumentTypeError("answer yes or no")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Log and summarise the two-block stack test")
    commands = parser.add_subparsers(dest="command", required=True)
    add = commands.add_parser("add", help="log one run")
    summarise = commands.add_parser("summary", help="how the latest 10 runs went")
    for sub in (add, summarise):
        sub.add_argument("--file", default=str(TRIALS_FILE), help="the log (default docs/trials.csv)")
    for name in ("top-found", "bottom-found", "top-removed"):
        add.add_argument(f"--{name}", type=_yes_no_arg, required=True, metavar="yes|no")
    for name in ("before-x", "before-y", "before-deg", "after-x", "after-y", "after-deg"):
        add.add_argument(f"--{name}", type=float)
    add.add_argument("--notes", default="")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    if args.command == "summary":
        print(format_summary(summary(Path(args.file))))
        return 0

    numbers = [args.before_x, args.before_y, args.before_deg, args.after_x, args.after_y, args.after_deg]
    if any(n is not None for n in numbers) and any(n is None for n in numbers):
        print("Give all of --before-x --before-y --before-deg --after-x --after-y --after-deg, or none of them.",
              file=sys.stderr)
        return 1
    measured = all(n is not None for n in numbers)
    try:
        config = load_config()
    except ValueError as error:
        print(f"Config problem: {error}", file=sys.stderr)
        return 1
    row = log_trial(
        Path(args.file),
        top_found=args.top_found, bottom_found=args.bottom_found, top_removed=args.top_removed,
        before_xy=(args.before_x, args.before_y) if measured else None,
        after_xy=(args.after_x, args.after_y) if measured else None,
        before_deg=args.before_deg, after_deg=args.after_deg,
        notes=args.notes, max_shift_mm=config.max_shift_mm, max_rotation_deg=config.max_rotation_deg,
    )
    print(f"Trial {row['trial']}: {'PASS' if row['pass'] == 'yes' else 'FAIL'}"
          + (f" ({row['failure_cause']})" if row["failure_cause"] else ""))
    print(format_summary(summary(Path(args.file))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
