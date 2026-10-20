"""Learning from past runs, in the smallest honest way.

After a run that bumped something (the rover said it brushed a block, its own sensor hit an obstacle
more often than the picks explain, or a block we were not touching got knocked), the corridor the planner leaves around blocks gets a little wider.
After clean runs the old trouble ages out of a short window and the extra room goes away again.

It can only ever add room on top of the configured clearance, never take any away, and the
extra room is capped. Runs that say nothing about the path (stopped by the operator, or
unverified with no bump) are not recorded at all. The whole state is a short list in one JSON
file, so a person can read it and delete it.
"""

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

DEFAULT_WINDOW = 10
DEFAULT_STEP_MM = 10.0
DEFAULT_MAX_EXTRA_MM = 30.0
BUMPED = "the rover hit something"
KNOCKED = "a block it was not touching was knocked"


@dataclass(frozen=True)
class Run:
    run_id: str
    trouble: bool
    why: str = ""


class Experience:
    def __init__(
        self,
        path: Optional[Path] = None,
        *,
        window: int = DEFAULT_WINDOW,
        step_mm: float = DEFAULT_STEP_MM,
        max_extra_mm: float = DEFAULT_MAX_EXTRA_MM,
    ) -> None:
        if window < 1:
            raise ValueError("window must be at least 1")
        if step_mm < 0 or max_extra_mm < 0:
            raise ValueError("step_mm and max_extra_mm must not be negative")
        self._path = Path(path) if path is not None else None
        self._window = window
        self._step = float(step_mm)
        self._max = float(max_extra_mm)
        self._runs: list[Run] = self._load()

    # ---- what it has learned -----------------------------------------------------
    @property
    def runs(self) -> tuple[Run, ...]:
        return tuple(self._runs)

    @property
    def extra_clearance_mm(self) -> float:
        """Room to add on each side of the buggy, on top of the configured clearance."""
        return min(self._max, self._step * self._troubles())

    @property
    def explanation(self) -> Optional[str]:
        """One sentence for the operator page, or None while nothing has changed."""
        extra = self.extra_clearance_mm
        if extra <= 0:
            return None
        total = len(self._runs)
        history = "the last run had trouble" if total == 1 else f"{self._troubles()} of the last {total} runs had trouble"
        return f"Corridor widened by {extra:.0f} mm each side: {history}."

    def _troubles(self) -> int:
        return sum(1 for run in self._runs if run.trouble)

    # ---- learning ----------------------------------------------------------------
    def record(self, facts: dict[str, Any], disturbed: bool = False) -> Optional[Run]:
        """Take in a finished run. Returns what was recorded, or None if it says nothing."""
        run = self._judge(facts, disturbed)
        if run is None or any(old.run_id == run.run_id for old in self._runs):
            return None
        self._runs = (self._runs + [run])[-self._window :]
        self._save()
        return run

    @staticmethod
    def _judge(facts: dict[str, Any], disturbed: bool) -> Optional[Run]:
        run_id = str(facts.get("run_id", ""))
        if not run_id or facts.get("status") == "running":
            return None
        # The rover stops for an obstacle each time it closes in on a block to pick it, so one
        # stop per pick is normal. Only stops beyond that mean it met something it did not plan for.
        expected_stops = facts.get("steps_planned", 0) // 2
        if facts.get("bumped") or facts.get("obstacles_detected", 0) > expected_stops:
            return Run(run_id, True, BUMPED)
        if disturbed:
            return Run(run_id, True, KNOCKED)
        if facts.get("status") == "completed" and facts.get("verified") is True:
            return Run(run_id, False)
        return None

    # ---- the file ----------------------------------------------------------------
    def _load(self) -> list[Run]:
        if self._path is None or not self._path.exists():
            return []
        try:
            entries = json.loads(self._path.read_text(encoding="utf-8")).get("runs", [])
        except (OSError, ValueError, AttributeError):
            return []  # unreadable: start empty rather than refuse to run
        runs = []
        for entry in entries if isinstance(entries, list) else []:
            if (
                isinstance(entry, dict)
                and isinstance(entry.get("run_id"), str)
                and isinstance(entry.get("trouble"), bool)
            ):
                runs.append(Run(entry["run_id"], entry["trouble"], str(entry.get("why", ""))))
        return runs[-self._window :]

    def _save(self) -> None:
        if self._path is None:
            return
        data = {"runs": [{"run_id": r.run_id, "trouble": r.trouble, "why": r.why} for r in self._runs]}
        temporary = self._path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(temporary, self._path)  # a crash mid-write never leaves half a file
