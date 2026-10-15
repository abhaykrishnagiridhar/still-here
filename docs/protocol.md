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

## Proposed clarifications (all four must agree before the draft above changes)

Nothing above is changed. These describe what the laptop code and the software rover (`laptop/sim_rover.py`) already do, written down so the firmware can match them exactly. Each one is tested on the laptop side.

1. **`plan_id` is a positive whole number**, as in `models.Plan`. A text id such as `"run-001"` is refused by the rover as `bad_plan`.
2. **Confirming a plan.** After a `plan` message the rover answers `event: plan_stored`, and its next `state` messages carry that `plan_id`. The laptop sends `plan_start` only when it sees a `state` with the same `plan_id`. If none arrives within 3 seconds it sends `abort` and tells the operator. (This is what "receive an `ok` state" means in practice.)
3. **Event codes in use.** `plan_stored` (`detail`: "N steps"), `bad_plan`, `aborted`, `link_lost`, `link_restored`, `plan_finished`. If the plan finished while the link was down, `plan_finished` is sent after `link_restored`.
4. **`step_done.reason`** when `ok` is false: `unreachable` (the pose cannot be reached) or `no block under the gripper`. When `ok` is true it is an empty string.
5. **Manual commands during a plan.** While a stored plan is running, `drive` and `arm_pose` are ignored. `abort` always works.
6. **Missing sensors.** The right flame sensor and the DHT11 have no pin yet. The rover should send `null` for a reading it cannot take. The laptop treats `null` as unknown.
7. **Who may connect.** The rover refuses a WebSocket connection whose `Origin` header names a site outside this machine or the local network (the same rule as `laptop/origin_guard.py`), and serves one operator at a time. Without this, any web page open on the same Wi-Fi could try to drive the rover.
8. **The rover's name.** It announces itself on the network as `still-here` (mDNS), so the laptop reaches it at `still-here.local`, port 81 for commands and port 80 for `/stream`.
9. **Limits.** Joint ranges are as in `laptop/plan_message.py` (`ARM_LIMITS_DEG`); the firmware should refuse anything outside them. The elbow reaches 135 degrees each way.

10. **`bad_plan` details.** `could not read plan`, `unknown action`, `too many steps`, `a plan is running` (a new `plan` is refused while one runs), `no stored plan with that id`, `battery too low`.
11. **Limits.** A message is at most 6144 bytes, a plan at most 32 steps, and step ids in a plan are unique. Anything longer, or not valid JSON, is ignored.
12. **More event codes.** `battery_low` (pack under 6.8 V) and `battery_critical` (under 6.4 V: the motors stop and `drive`, `arm_pose` and `plan_start` are refused until the pack is back above 7.0 V), each with the voltage in `detail`. `obstacle` (`left` or `right`) when an IR obstacle sensor stops forward driving. `battery_v` is `null` until the pack-voltage divider is fitted.
13. **`state.status`** is `running` while a plan runs, `holding` while a block is carried, `idle` otherwise. `step_id` is `null` when no plan is running.
14. **Wheels and arm.** The wheels ramp to speed over about 200 ms. The wheels and the arm never move at the same moment: the last command wins, and `arm_pose` stops the wheels first. A closed connection stops the wheels at once when no plan is running.
