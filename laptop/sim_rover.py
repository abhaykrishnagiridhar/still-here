"""A software stand-in for the rover firmware: same messages as docs/protocol.md, no hardware.

Pure logic with an explicit clock. Call `handle(message)` for each laptop message and
`step(dt)` to advance time; both return the messages the rover would send back.

Geometry numbers below are ASSUMPTIONS until the real arm is measured. Change them in one place.
Arm frame: origin at the arm base on the table, x forward, y left, z up (mm, degrees).
"""

from dataclasses import dataclass, replace
from math import acos, atan2, cos, degrees, hypot, pi, radians, sin
from typing import Optional, Sequence

from models import Block, HeatZone, PlanStep

# --- assumed geometry (mm) -------------------------------------------------------------
ARM_BASE_HEIGHT = 60.0
ARM_LINK_1 = 105.0
ARM_LINK_2 = 105.0
ARM_MOUNT_X = 0.0  # arm base sits over the rover centre
WHEEL_BASE = 140.0
MAX_SPEED_MM_S = 200.0
BLOCK_SIZE = 40.0

# --- joint limits and speeds (degrees) -------------------------------------------------
BASE_LIMITS = (-90.0, 90.0)
SHOULDER_LIMITS = (0.0, 120.0)
ELBOW_LIMITS = (-135.0, 135.0)  # 270 degrees: more than a standard 180 degree servo gives, so check it on the real arm
GRIPPER_LIMITS = (0.0, 90.0)  # 0 closed, 90 open
SERVO_RATE_DPS = 120.0  # at speed 1.0
POSE_TOLERANCE_DEG = 1.0

# --- timing and reach ------------------------------------------------------------------
LINK_TIMEOUT_S = 2.0
STATE_PERIOD_S = 0.2
SENSOR_PERIOD_S = 0.5
GRAB_REACH_MM = 35.0
HOVER_MM = 60.0
IR_RANGE_MM = 150.0

HOME_POSE = {"base": 0.0, "shoulder": 60.0, "elbow": -90.0, "gripper": 90.0}
JOINTS = ("base", "shoulder", "elbow", "gripper")
_LIMITS = {
    "base": BASE_LIMITS,
    "shoulder": SHOULDER_LIMITS,
    "elbow": ELBOW_LIMITS,
    "gripper": GRIPPER_LIMITS,
}


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def clamp_pose(pose: dict) -> dict:
    return {j: clamp(float(pose[j]), *_LIMITS[j]) for j in JOINTS}


def arm_tip(pose: dict) -> tuple[float, float, float]:
    """Gripper tip in the arm frame for a joint pose (forward kinematics)."""
    shoulder = radians(pose["shoulder"])
    upper = shoulder + radians(pose["elbow"])
    reach = ARM_LINK_1 * cos(shoulder) + ARM_LINK_2 * cos(upper)
    height = ARM_BASE_HEIGHT + ARM_LINK_1 * sin(shoulder) + ARM_LINK_2 * sin(upper)
    base = radians(pose["base"])
    return (reach * cos(base), reach * sin(base), height)


def solve_pose(x: float, y: float, z: float, gripper: float) -> Optional[dict]:
    """Joint angles that put the tip at (x, y, z), elbow up, or None if out of reach."""
    reach = hypot(x, y)
    rise = z - ARM_BASE_HEIGHT
    dist = hypot(reach, rise)
    if dist < 1e-6 or dist > ARM_LINK_1 + ARM_LINK_2 or dist < abs(ARM_LINK_1 - ARM_LINK_2):
        return None
    inner = acos(clamp((ARM_LINK_1**2 + ARM_LINK_2**2 - dist**2) / (2 * ARM_LINK_1 * ARM_LINK_2), -1, 1))
    lift = acos(clamp((ARM_LINK_1**2 + dist**2 - ARM_LINK_2**2) / (2 * ARM_LINK_1 * dist), -1, 1))
    pose = {
        "base": degrees(atan2(y, x)),
        "shoulder": degrees(atan2(rise, reach) + lift),
        "elbow": degrees(inner - pi),
        "gripper": gripper,
    }
    in_limits = all(_LIMITS[j][0] - 1e-6 <= pose[j] <= _LIMITS[j][1] + 1e-6 for j in JOINTS)
    return pose if in_limits else None


@dataclass(frozen=True)
class WorldBlock:
    block: Block
    z: float = BLOCK_SIZE / 2  # centre height; follows the gripper while carried


@dataclass(frozen=True)
class _Action:
    """One move of the plan runner: go to a pose, then optionally grab or release."""

    pose: dict
    then: Optional[str] = None  # "grab" | "release" | None


class SimRover:
    def __init__(
        self,
        blocks: Sequence[Block] = (),
        heat_zones: Sequence[HeatZone] = (),
        survivor: Optional[tuple[float, float]] = None,
    ):
        self.t = 0.0
        self.x = 0.0  # world position of the rover centre (mm)
        self.y = 0.0
        self.heading = 0.0  # radians, 0 = world +x, positive = left
        self.mode = "manual"
        self.wheels = (0.0, 0.0)
        self.pose = dict(HOME_POSE)
        self._target = dict(HOME_POSE)
        self._speed = 1.0
        self.blocks = {b.id: WorldBlock(b) for b in blocks}
        self.heat_zones = tuple(heat_zones)
        self.survivor = survivor
        self.carrying: Optional[int] = None
        self.battery_v = 8.2
        self._last_ping = 0.0
        self._link_up = True
        self._next_state = 0.0
        self._next_sensors = 0.0
        self._stored: Optional[tuple[int, tuple[PlanStep, ...]]] = None
        self._running = False
        self._step_index = 0
        self._actions: list[_Action] = []
        self._current_step: Optional[PlanStep] = None
        self._step_failure: Optional[str] = None
        self._finished_offline = False

    # ------------------------------------------------------------------ frames
    def to_arm_frame(self, wx: float, wy: float) -> tuple[float, float]:
        dx, dy = wx - self.x, wy - self.y
        c, s = cos(self.heading), sin(self.heading)
        return (dx * c + dy * s - ARM_MOUNT_X, -dx * s + dy * c)

    def to_world(self, ax: float, ay: float) -> tuple[float, float]:
        c, s = cos(self.heading), sin(self.heading)
        lx = ax + ARM_MOUNT_X
        return (self.x + lx * c - ay * s, self.y + lx * s + ay * c)

    def tip_world(self) -> tuple[float, float, float]:
        ax, ay, az = arm_tip(self.pose)
        wx, wy = self.to_world(ax, ay)
        return (wx, wy, az)

    # ------------------------------------------------------------------ incoming
    def handle(self, message: dict) -> list[dict]:
        handler = {
            "ping": self._on_ping,
            "mode": self._on_mode,
            "drive": self._on_drive,
            "arm_pose": self._on_arm_pose,
            "plan": self._on_plan,
            "plan_start": self._on_plan_start,
            "abort": self._on_abort,
        }.get(message.get("type"))
        return handler(message) if handler else []  # unknown types are ignored

    def _on_ping(self, message: dict) -> list[dict]:
        self._last_ping = self.t
        if self._link_up:
            return []
        self._link_up = True
        out = [{"type": "event", "code": "link_restored", "detail": ""}]
        if self._finished_offline:
            self._finished_offline = False
            out.append({"type": "event", "code": "plan_finished", "detail": "finished while link was down"})
        return out

    def _on_mode(self, message: dict) -> list[dict]:
        if message.get("mode") in ("manual", "auto"):
            self.mode = message["mode"]
        return []

    def _on_drive(self, message: dict) -> list[dict]:
        if self._running:
            return []  # the stored plan owns the robot until it ends or is aborted
        try:
            self.wheels = (
                clamp(float(message.get("left", 0.0)), -1, 1),
                clamp(float(message.get("right", 0.0)), -1, 1),
            )
        except (TypeError, ValueError):
            pass
        return []

    def _on_arm_pose(self, message: dict) -> list[dict]:
        if self._running:
            return []
        try:
            self._target = clamp_pose({j: message.get(j, self._target[j]) for j in JOINTS})
            self._speed = clamp(float(message.get("speed", 1.0)), 0.05, 1.0)
        except (TypeError, ValueError):
            pass
        return []

    def _on_plan(self, message: dict) -> list[dict]:
        try:
            steps = tuple(
                PlanStep(int(s["id"]), s["action"], float(s["x"]), float(s["y"]), float(s["z"]))
                for s in message["steps"]
            )
            plan_id = int(message["plan_id"])
        except (KeyError, TypeError, ValueError):
            return [{"type": "event", "code": "bad_plan", "detail": "could not read plan"}]
        if any(s.action not in ("pick", "drop") for s in steps):
            return [{"type": "event", "code": "bad_plan", "detail": "unknown action"}]
        self._stored = (plan_id, steps)
        return [{"type": "event", "code": "plan_stored", "detail": f"{len(steps)} steps"}]

    def _on_plan_start(self, message: dict) -> list[dict]:
        if self._stored is None or self._stored[0] != message.get("plan_id"):
            return [{"type": "event", "code": "bad_plan", "detail": "no stored plan with that id"}]
        self._running = True
        self._step_index = 0
        self.wheels = (0.0, 0.0)
        self._begin_step()
        return []

    def _on_abort(self, message: dict) -> list[dict]:
        self._running = False
        self._actions = []
        self._current_step = None
        self.wheels = (0.0, 0.0)
        self._target = dict(self.pose)
        return [{"type": "event", "code": "aborted", "detail": ""}]

    # ------------------------------------------------------------------ plan runner
    def _begin_step(self) -> None:
        steps = self._stored[1] if self._stored else ()
        if self._step_index >= len(steps):
            self._running = False
            self._current_step = None
            self._target = dict(HOME_POSE)
            return
        step = steps[self._step_index]
        self._current_step = step
        picking = step.action == "pick"
        hold = GRIPPER_LIMITS[1] if picking else GRIPPER_LIMITS[0]
        hover = solve_pose(step.x, step.y, step.z + HOVER_MM, hold)
        down = solve_pose(step.x, step.y, step.z, hold)
        if hover is None or down is None:
            self._actions = []
            self._step_failure = "unreachable"
            return
        self._step_failure = None
        end_grip = GRIPPER_LIMITS[0] if picking else GRIPPER_LIMITS[1]
        self._actions = [
            _Action(hover),
            _Action(down, then="grab" if picking else "release"),
            _Action({**down, "gripper": end_grip}),
            _Action({**hover, "gripper": end_grip}),
        ]

    def _finish_step(self, ok: bool, reason: str) -> list[dict]:
        out = [
            {
                "type": "step_done",
                "plan_id": self._stored[0],
                "step_id": self._current_step.id,
                "ok": ok,
                "reason": reason,
            }
        ]
        self._step_index += 1
        self._begin_step()
        if not self._running:
            if self._link_up:
                out.append({"type": "event", "code": "plan_finished", "detail": ""})
            else:
                self._finished_offline = True
        return out

    def _do_then(self, verb: Optional[str]) -> tuple[bool, str]:
        if verb == "grab":
            tx, ty, tz = self.tip_world()
            near = [
                (hypot(wb.block.x - tx, wb.block.y - ty), wb.block.id)
                for wb in self.blocks.values()
                if wb.block.id != self.carrying and abs(wb.z - tz) <= GRAB_REACH_MM
            ]
            near = [n for n in near if n[0] <= GRAB_REACH_MM]
            if not near:
                return False, "no block under the gripper"
            self.carrying = min(near)[1]
        elif verb == "release":
            self.carrying = None
        return True, ""

    # ------------------------------------------------------------------ time
    def step(self, dt: float) -> list[dict]:
        self.t += dt
        out: list[dict] = []
        if self._link_up and self.t - self._last_ping > LINK_TIMEOUT_S:
            self._link_up = False
            out.append({"type": "event", "code": "link_lost", "detail": ""})
            if not self._running:
                self.wheels = (0.0, 0.0)  # no plan running: stop wheels, hold the arm
                self._target = dict(self.pose)
        self._drive(dt)
        reached = self._move_arm(dt)
        self._carry()
        if self._running:
            out.extend(self._advance_plan(reached))
        self.battery_v = max(6.0, self.battery_v - 0.0002 * dt)
        if self.t >= self._next_state:
            self._next_state += STATE_PERIOD_S
            out.append(self.state_message())
        if self.t >= self._next_sensors:
            self._next_sensors += SENSOR_PERIOD_S
            out.append(self.sensors_message())
        return out

    def _drive(self, dt: float) -> None:
        left, right = self.wheels
        forward = (left + right) / 2 * MAX_SPEED_MM_S
        turn = (right - left) * MAX_SPEED_MM_S / WHEEL_BASE  # rad/s, positive = left turn
        self.heading += turn * dt
        self.x += forward * cos(self.heading) * dt
        self.y += forward * sin(self.heading) * dt

    def _move_arm(self, dt: float) -> bool:
        if self._running and self._actions:
            self._target = self._actions[0].pose
        step_deg = SERVO_RATE_DPS * self._speed * dt
        at_target = True
        for joint in JOINTS:
            error = self._target[joint] - self.pose[joint]
            self.pose[joint] += clamp(error, -step_deg, step_deg)
            if abs(self._target[joint] - self.pose[joint]) > POSE_TOLERANCE_DEG:
                at_target = False
        return at_target

    def _carry(self) -> None:
        if self.carrying is None:
            return
        tx, ty, tz = self.tip_world()
        wb = self.blocks[self.carrying]
        self.blocks[self.carrying] = WorldBlock(replace(wb.block, x=tx, y=ty), z=tz)

    def _advance_plan(self, reached: bool) -> list[dict]:
        if self._current_step is None:
            return []
        if not self._actions:
            return self._finish_step(False, self._step_failure or "unreachable")
        if not reached:
            return []
        action = self._actions.pop(0)
        ok, reason = self._do_then(action.then)
        if not ok:
            self._actions = []
            return self._finish_step(False, reason)
        if not self._actions:
            return self._finish_step(True, "")
        return []

    # ------------------------------------------------------------------ outgoing
    def state_message(self) -> dict:
        return {
            "type": "state",
            "t": round(self.t, 3),
            "mode": self.mode,
            "arm": {j: round(self.pose[j], 2) for j in JOINTS},
            "plan_id": self._stored[0] if self._stored else None,
            "step_id": self._current_step.id if self._current_step else None,
            "status": "running" if self._running else ("holding" if self.carrying is not None else "idle"),
        }

    def sensors_message(self) -> dict:
        def obstacle(side: float) -> bool:
            for wb in self.blocks.values():
                if wb.block.id == self.carrying:
                    continue
                ax, ay = self.to_arm_frame(wb.block.x, wb.block.y)
                if 0 < ax <= IR_RANGE_MM and abs(ay - side * 50.0) <= 50.0:
                    return True
            return False

        def flame(side: float) -> bool:
            px, py = self.to_world(0.0, side * 40.0)
            return any(hypot(px - z.x, py - z.y) <= z.radius for z in self.heat_zones)

        return {
            "type": "sensors",
            "ir_obstacle": {"left": obstacle(1.0), "right": obstacle(-1.0)},
            "ir_flame": {"left": flame(1.0), "right": flame(-1.0)},
            "dht": {"temp_c": 24.0, "hum_pct": 50.0},
            "battery_v": round(self.battery_v, 2),
        }

    def snapshot(self) -> dict:
        """Everything the 3D viewer needs, in the world frame."""
        return {
            "rover": {"x": self.x, "y": self.y, "heading": self.heading},
            "arm": dict(self.pose),
            "tip": self.tip_world(),
            "blocks": [
                {
                    "id": wb.block.id,
                    "x": wb.block.x,
                    "y": wb.block.y,
                    "z": wb.z,
                    "layer": wb.block.layer,
                    "heavy": wb.block.weight_class == "heavy",
                    "carried": wb.block.id == self.carrying,
                }
                for wb in self.blocks.values()
            ],
            "heat": [{"x": z.x, "y": z.y, "r": z.radius} for z in self.heat_zones],
            "survivor": self.survivor,
            "link_up": self._link_up,
            "t": self.t,
        }
