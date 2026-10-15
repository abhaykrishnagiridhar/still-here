"""What the person at the laptop sees and may do: check the plan, approve it, watch it run.

No network and no camera in here, so it can be tested on its own. The server feeds it what
the camera pipeline decided (`observe`) and what the rover said (`on_rover`), and it sends
messages to the rover through a link with one method, `send(message)`.

The safety rules:
- Only the plan the person was shown can be approved. If the picture changed since, the
  approval is refused and they must look again.
- The plan is sent first and started only once the rover's own state shows that plan's id
  (docs/protocol.md: the rover must confirm before `plan_start`).
- Once approved, new pictures no longer change the plan. The rover runs exactly what was approved.
"""

import hashlib
import json
import time
from dataclasses import dataclass
from typing import Callable, Optional, Protocol

from route import RoutePlan

# Where picked blocks are put down, in the arm frame (mm). An assumption until the rover is built.
DROP_POINT_MM = (100.0, -90.0)
BLOCK_HEIGHT_MM = 40.0
CONFIRM_TIMEOUT_S = 3.0  # how long the rover has to confirm a plan before it is cancelled


class Link(Protocol):
    def send(self, message: dict) -> None: ...


@dataclass(frozen=True)
class Outcome:
    ok: bool
    message: str


def _plan_view(result: RoutePlan) -> dict:
    order = [
        {"n": n, "id": b.id, "x": round(b.x, 1), "y": round(b.y, 1)}
        for n, b in enumerate(result.order, start=1)
    ]
    left = [{"id": item.block.id, "reason": item.reason} for item in result.left]
    identity = json.dumps([[o["id"] for o in order], [[i["id"], i["reason"]] for i in left], result.ok])
    return {
        "key": hashlib.sha1(identity.encode()).hexdigest()[:12],
        "ok": result.ok,
        "note": result.note,
        "order": order,
        "left": left,
        "path": [[round(x, 1), round(y, 1)] for x, y in result.path],
    }


class Operator:
    def __init__(
        self,
        link: Link,
        *,
        block_mm: float = BLOCK_HEIGHT_MM,
        drop_mm: tuple[float, float] = DROP_POINT_MM,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._link = link
        self._block_mm = block_mm
        self._drop = drop_mm
        self._clock = clock
        # Unique per start, so a plan the rover still holds from an earlier session is never mistaken for this one.
        self._next_plan_id = int(clock() * 10) % 1_000_000 + 1
        self._survivor_hint: Optional[tuple[int, int]] = None
        self._reset_run()

    # ---- run bookkeeping ---------------------------------------------------------
    def _reset_run(self) -> None:
        self._latest = None  # what the camera pipeline last decided
        self._phase = "scanning"
        self._frozen: Optional[dict] = None  # the plan that was approved
        self._frozen_survivor: Optional[tuple[float, float]] = None
        self._steps: list[dict] = []
        self._results: dict[int, tuple[bool, str]] = {}
        self._plan_id: Optional[int] = None
        self._approved_at = 0.0
        self._note = ""
        self._link_up = True

    def reset(self) -> None:
        """Start a fresh run. The tapped survivor is forgotten with it."""
        self._reset_run()
        self._survivor_hint = None

    # ---- the survivor the person tapped ------------------------------------------
    @property
    def survivor_hint(self) -> Optional[tuple[int, int]]:
        return self._survivor_hint

    def tap_survivor(self, x: float, y: float) -> None:
        self._survivor_hint = (round(x), round(y))

    def clear_survivor(self) -> None:
        self._survivor_hint = None

    # ---- what the camera sees ----------------------------------------------------
    def observe(self, seen) -> None:
        if self._phase in ("waiting", "running"):
            return  # the approved plan is not changed by what the camera sees now
        self._latest = seen

    def latest_blocks(self) -> tuple:
        """The blocks (in millimetres) in the newest picture, for a simulated rover to copy."""
        scene = getattr(self._latest, "scene", None)
        return tuple(scene.blocks) if scene is not None else ()

    def _assess(self) -> tuple[str, str, Optional[dict], bool]:
        """(phase, message, plan view, can approve) from the latest picture."""
        seen = self._latest
        if seen is None or seen.result is None:
            return "scanning", "Looking for blocks and the survivor light.", None, False
        result = seen.result
        if not isinstance(result, RoutePlan):
            return "need_survivor", "Survivor not found. Tap it in the picture.", None, False
        view = _plan_view(result)
        if not result.ok:
            return "blocked", f"No safe way to the survivor: {result.note}.", view, False
        if not result.order:
            return "clear", "The way to the survivor is already clear. Nothing to remove.", view, False
        count = len(result.order)
        plural = "s" if count != 1 else ""
        return "plan_ready", f"{count} block{plural} to remove. Check the plan, then approve.", view, True

    # ---- approving ---------------------------------------------------------------
    def approve(self, key: str) -> Outcome:
        if self._phase in ("waiting", "running", "done", "aborted"):
            return Outcome(False, "A plan has already been approved. Start a new run first.")
        _, _, view, can_approve = self._assess()
        if not can_approve or view is None:
            return Outcome(False, "There is no plan to approve yet.")
        if key != view["key"]:
            return Outcome(False, "The plan changed since you looked. Check it again.")
        steps: list[dict] = []
        for item in view["order"]:
            for action, x, y in (("pick", item["x"], item["y"]), ("drop", self._drop[0], self._drop[1])):
                steps.append({"id": len(steps) + 1, "action": action, "x": x, "y": y, "z": self._block_mm / 2})
        self._plan_id = self._next_plan_id
        self._next_plan_id += 1
        self._steps = steps
        self._frozen = view
        path = self._latest.result.path
        self._frozen_survivor = path[-1] if path else None
        self._results = {}
        self._approved_at = self._clock()
        self._phase = "waiting"
        self._note = "Waiting for the rover to confirm the plan."
        self._link.send({"type": "plan", "plan_id": self._plan_id, "steps": steps})
        return Outcome(True, self._note)

    def abort(self) -> None:
        self._link.send({"type": "abort"})
        if self._phase in ("waiting", "running"):
            self._phase = "aborted"
            self._note = "Stopped by the operator."

    def tick(self) -> None:
        """Call regularly: gives up on a rover that never confirms the plan."""
        if self._phase == "waiting" and self._clock() - self._approved_at > CONFIRM_TIMEOUT_S:
            self._link.send({"type": "abort"})
            self._phase = "aborted"
            self._note = "The rover did not confirm the plan, so it was cancelled."

    # ---- what the rover says -----------------------------------------------------
    def on_rover(self, messages: list[dict]) -> None:
        for message in messages:
            kind = message.get("type")
            if kind == "state":
                self._on_state(message)
            elif kind == "step_done" and message.get("plan_id") == self._plan_id:
                self._results[message["step_id"]] = (bool(message["ok"]), message.get("reason", ""))
            elif kind == "event":
                self._on_event(message.get("code"))

    def _on_state(self, message: dict) -> None:
        if self._phase == "waiting" and message.get("plan_id") == self._plan_id:
            self._link.send({"type": "plan_start", "plan_id": self._plan_id})
            self._phase = "running"
            self._note = "Running the approved plan."

    def _on_event(self, code: Optional[str]) -> None:
        if code == "plan_finished" and self._phase == "running":
            self._phase = "done"
            self._note = "The rover finished the plan."
        elif code == "aborted" and self._phase in ("waiting", "running"):
            self._phase = "aborted"
            self._note = "The rover stopped."
        elif code == "bad_plan":
            self._phase = "aborted"
            self._note = "The rover refused the plan."
        elif code == "link_lost":
            self._link_up = False
        elif code == "link_restored":
            self._link_up = True

    # ---- what the page shows -----------------------------------------------------
    def state(self) -> dict:
        if self._phase in ("waiting", "running", "done", "aborted"):
            phase, message, view, can_approve = self._phase, self._note, self._frozen, False
        else:
            phase, message, view, can_approve = self._assess()
        if not self._link_up:
            message = "Link to the rover lost. It carries on with the stored plan. " + message
        survivor = self._latest.survivor if self._latest is not None else self._survivor_hint
        return {
            "phase": phase,
            "message": message,
            "can_approve": can_approve,
            "survivor_px": list(survivor) if survivor is not None else None,
            "plan": view,
            "progress": {"done": len(self._results), "total": len(self._steps)},
            "link_up": self._link_up,
        }

    # ---- the report --------------------------------------------------------------
    def report(self) -> dict:
        if self._frozen is None:
            return {"outcome": "not_run", "survivor_mm": None, "picked": [], "left": [], "note": ""}
        picked = []
        for item in self._frozen["order"]:
            pick, drop = 2 * item["n"] - 1, 2 * item["n"]
            results = [self._results.get(pick), self._results.get(drop)]
            failed = next((r for r in results if r is not None and not r[0]), None)
            if failed is not None:
                ok, reason = False, failed[1] or "failed"
            elif None in results:
                ok, reason = False, "not done"
            else:
                ok, reason = True, ""
            picked.append({"id": item["id"], "x": item["x"], "y": item["y"], "ok": ok, "reason": reason})
        survivor = list(self._frozen_survivor) if self._frozen_survivor is not None else None
        return {
            "outcome": self._phase,
            "survivor_mm": survivor,
            "picked": picked,
            "left": self._frozen["left"],
            "note": self._frozen["note"],
        }

    def report_text(self) -> str:
        report = self.report()
        if report["outcome"] == "not_run":
            return "No run has happened yet.\n"
        lines = [f"Run {report['outcome']}."]
        if report["note"]:
            lines.append(report["note"][0].upper() + report["note"][1:] + ".")
        if report["survivor_mm"] is not None:
            x, y = report["survivor_mm"]
            lines.append(f"Survivor at ({x:.0f}, {y:.0f}) mm from the rover.")
        for item in report["picked"]:
            where = f"block_{item['id']} at ({item['x']:.0f}, {item['y']:.0f}) mm"
            status = "moved out of the way" if item["ok"] else f"not moved ({item['reason']})"
            lines.append(f"{where}: {status}")
        for item in report["left"]:
            lines.append(f"block_{item['id']}: left in place, {item['reason']}")
        return "\n".join(lines) + "\n"
