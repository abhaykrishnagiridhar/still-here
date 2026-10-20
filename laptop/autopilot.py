"""Autonomous mode for the simulation: the laptop approves its own plans, run after run, and learns.

Normally a person reads each plan and presses Approve. For a demonstration in the Blender twin this module does
that part, so the whole loop can be seen without anyone clicking: look, plan, approve, run, check, learn, and
go again on the same course. Each run is written down, so the improvement from one run to the next is visible.

The safety rules stay:
- It only exists for a simulated rover. server.py refuses it with the real one.
- It waits a few seconds on every plan before approving, so a person watching can read it.
- It approves only a plan that stayed the same for that whole wait.
- Anything that stops a run (a person pressing Stop, the rover refusing a plan, a lost link) switches it off,
  and it stays off until the server is started again. It never carries on after a stop.

It talks to the twin with two messages: `reset_world` (put the course back as it was) and `overlay` (what to
write on the board in the 3D view: the run number, the corridor and what was learned).
"""

import time
from typing import Callable, Optional

from operator_core import Operator

THINK_S = 2.5  # how long a plan is shown before it is approved
PAUSE_S = 4.0  # how long a finished run's result is shown before the course is reset
RESEND_OVERLAY_S = 2.0  # the twin may have been restarted, so the board is sent again now and then

CLEAN = "clean"
BUMPED = "bumped"
UNVERIFIED = "unverified"


class Autopilot:
    def __init__(
        self,
        operator: Operator,
        link,
        *,
        episodes: int = 3,
        extra_clearance: Callable[[], float] = lambda: 0.0,
        corridor_mm: float = 240.0,
        clock: Callable[[], float] = time.monotonic,
        think_s: float = THINK_S,
        pause_s: float = PAUSE_S,
    ) -> None:
        if episodes < 1:
            raise ValueError("episodes must be at least 1")
        self._operator = operator
        self._link = link
        self._episodes = episodes
        self._extra = extra_clearance
        self._base_corridor = corridor_mm
        self._clock = clock
        self._think_s = think_s
        self._pause_s = pause_s
        self._episode = 1
        self._extra_at_start = float(extra_clearance())
        self._history: list[dict] = []
        self._active = True
        self._message = "Autonomous mode: looking at the scene."
        self._ready_key: Optional[str] = None
        self._ready_since = 0.0
        self._ended_at: Optional[float] = None
        self._last_overlay: Optional[dict] = None
        self._last_overlay_at = float("-inf")

    # ---- what the page and the twin are told ------------------------------------------
    @property
    def active(self) -> bool:
        return self._active

    def _corridor(self, extra_mm: float) -> float:
        return self._base_corridor + 2 * extra_mm

    def summary(self) -> dict:
        """Everything the operator page shows about autonomous mode."""
        history = []
        for index, entry in enumerate(self._history):
            later = self._history[index + 1] if index + 1 < len(self._history) else None
            next_corridor = later["corridor_mm"] if later is not None else self._corridor(float(self._extra()))
            history.append({**entry, "next_corridor_mm": next_corridor})
        return {
            "active": self._active,
            "episode": self._episode,
            "episodes": self._episodes,
            "message": self._message,
            "corridor_mm": self._corridor(self._extra_at_start),
            "extra_mm": float(self._extra()),
            "history": history,
        }

    def _caption(self) -> str:
        extra = float(self._extra())
        corridor = self._corridor(extra)
        text = f"Run {self._episode} of {self._episodes} | corridor {corridor:.0f} mm"
        if extra > 0:
            text += f" (+{extra:.0f} learned)"
        brushed = self._operator.brushed
        if brushed is not None:
            text += f" | brushed {brushed}"
        return text

    def _push_overlay(self, now: float) -> None:
        extra = float(self._extra())
        overlay = {
            "type": "overlay",
            "episode": self._episode,
            "episodes": self._episodes,
            "corridor_mm": self._corridor(extra),
            "extra_mm": extra,
            "brushed": self._operator.brushed,
            "active": self._active,
            "text": self._caption(),
        }
        if overlay != self._last_overlay or now - self._last_overlay_at >= RESEND_OVERLAY_S:
            self._link.send(overlay)
            self._last_overlay, self._last_overlay_at = overlay, now

    # ---- control -----------------------------------------------------------------------
    def stop(self, reason: str) -> None:
        """Switch autonomous mode off for good (until the server is restarted)."""
        self._active = False
        self._message = reason
        self._push_overlay(self._clock())

    def tick(self) -> None:
        """Call regularly (the server calls it with the rover loop)."""
        if not self._active:
            return
        now = self._clock()
        state = self._operator.state()
        phase = state["phase"]
        if phase == "plan_ready" and state["can_approve"]:
            self._consider(state["plan"]["key"], now)
        else:
            self._ready_key = None
            if phase == "done":
                self._after_the_run(now)
            elif phase == "aborted":
                self.stop("A run was stopped, so autonomous mode is off. A person decides what happens next.")
            elif phase in ("blocked", "need_survivor"):
                self._message = "Autonomous mode: waiting, there is no safe plan to approve yet."
            elif phase == "scanning":
                self._message = "Autonomous mode: looking at the scene."
        if self._active:
            self._push_overlay(now)

    def _consider(self, key: str, now: float) -> None:
        if key != self._ready_key:
            self._ready_key, self._ready_since = key, now
            self._message = "Autonomous mode: plan ready, checking it before approving."
            return
        if now - self._ready_since < self._think_s:
            return
        outcome = self._operator.approve(key)
        if outcome.ok:
            self._message = f"Autonomous mode: run {self._episode} of {self._episodes} approved and running."
        else:
            self._ready_since = now  # try again after another look
            self._message = f"Autonomous mode: the plan was not accepted ({outcome.message})"

    def _after_the_run(self, now: float) -> None:
        if self._ended_at is None:
            self._record()
            self._ended_at = now
            return
        if now - self._ended_at < self._pause_s:
            return
        if self._episode >= self._episodes:
            self._active = False
            self._message = f"All {self._episodes} runs finished. The result of each is listed below."
            return
        self._link.send({"type": "reset_world"})
        self._operator.reset()
        self._episode += 1
        self._extra_at_start = float(self._extra())
        self._ended_at = None
        self._message = f"Autonomous mode: run {self._episode} starts on the same course, using what it learned."

    def _record(self) -> None:
        facts = self._operator.facts() or {}
        if facts.get("bumped"):
            outcome = BUMPED
        elif facts.get("verified"):
            outcome = CLEAN
        else:
            outcome = UNVERIFIED
        self._history.append(
            {
                "number": self._episode,
                "moved": int(facts.get("steps_planned", 0)) // 2,
                "outcome": outcome,
                "brushed": self._operator.brushed,
                "corridor_mm": self._corridor(self._extra_at_start),
            }
        )
        self._message = {
            CLEAN: f"Run {self._episode} was clean: the way is clear and nothing was touched.",
            BUMPED: f"Run {self._episode}: the rover brushed {self._operator.brushed}. It will leave more room next time.",
            UNVERIFIED: f"Run {self._episode} finished, but the camera could not confirm the way is clear.",
        }[outcome]
