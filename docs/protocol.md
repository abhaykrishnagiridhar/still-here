# Laptop <-> Rover protocol (DRAFT v0)

Change this file only when all four team members agree. Units: millimetres, degrees, seconds.

## Transport

| What | Where |
|---|---|
| Commands and status | WebSocket `ws://<rover-ip>:81/`, JSON text messages, one object per message |
| Video | MJPEG at `http://<rover-ip>/stream` |

Every message has `"type"`. Unknown types are ignored, not errors.

## Coordinate frames

- **Arm frame:** origin at the arm base on the table, x forward, y left, z up (mm).
- **Camera frame:** image pixels. The laptop converts pixels to the arm frame using the calibration, so the rover only ever sees arm-frame targets.

## Laptop to rover

| type | Fields | Meaning |
|---|---|---|
| `ping` | `t` | Heartbeat, sent every 500 ms |
| `mode` | `mode`: `manual` or `auto` | Switch drive mode |
| `drive` | `left`, `right` in -1..1 | Manual wheel speeds |
| `arm_pose` | `base`, `shoulder`, `elbow`, `gripper` (degrees), `speed` 0..1 | Move the arm to a pose |
| `plan` | `plan_id`, `steps` (see below) | Store an approved plan on the rover |
| `plan_start` | `plan_id` | Begin executing the stored plan |
| `abort` | | Stop everything and hold safe pose |

A plan step: `{"id": 1, "action": "pick" | "drop", "x": 0, "y": 0, "z": 0}` (arm frame, mm).

## Rover to laptop

| type | Fields | Meaning |
|---|---|---|
| `state` | `t`, `mode`, `arm`, `plan_id`, `step_id`, `status` | Sent at 5 Hz |
| `sensors` | `ir_obstacle` (left, right), `ir_flame` (left, right), `dht` (temp_c, hum_pct), `battery_v` (pack volts, see `docs/power.md`) | Sent at 2 Hz |
| `step_done` | `plan_id`, `step_id`, `ok`, `reason` | A plan step finished or failed |
| `event` | `code`, `detail` | Notable events, e.g. `link_lost`, `plan_finished` |

## Link loss

If the rover hears no `ping` for 2 seconds:

- **Plan running:** keep executing the stored plan to the end, then send `event: plan_finished` when the link returns.
- **No plan running:** stop wheels, hold arm pose.

The laptop must send the whole plan with `plan` and receive an `ok` state before `plan_start`.

## Shared data model

Defined in `laptop/models.py`. Fields the planner depends on:

- `Block`: `id`, `marker_id`, `x`, `y`, `layer` (1 = bottom, 2 = top), `weight_class` (`light` or `heavy`), `load_bearing`, `supports` (ids of blocks resting on it)
- `HeatZone`: `x`, `y`, `radius`
- `Plan`: `plan_id`, ordered `steps`
