# Phone and Blender simulation: context for an LLM

This document explains one part of the STILL HERE repository: driving a simulated rover from a phone, shown live in Blender. It is written so a language model (or a new teammate) can understand, run, test and change this part without reading the rest of the project. Everything here was checked against the code.

**In scope:** the phone controller page, the tilt-to-command mapping, the bridge server, the UDP link, the software rover model it drives, and the Blender scene.
**Out of scope:** the camera and vision code, the planner, the operator web page (`laptop/server.py`), the ESP32 firmware and the power design. The operator page also reuses the software rover (`SimRover`), but that is a separate feature and is not described here.

## 1. What the project is, in four lines

STILL HERE is a hackathon rescue rover: a wheeled base with a 4-servo arm that removes blocks to clear a path to a survivor. The laptop plans, and the rover executes commands sent as JSON messages defined in `docs/protocol.md`. Real firmware does not accept those messages yet. The phone/Blender simulation lets the team drive and pose the arm of a software copy of the rover, using the same messages and the same arm geometry the firmware is meant to use.

## 2. The data path

```
Phone browser (simulation/phone_control.html)
   |  tilt sensors -> JSON sample, about 60 per second
   |  WebSocket  ws://<laptop-ip>:8765/phone
   v
Bridge server (simulation/phone_bridge.py, FastAPI, port 8765)
   |  GyroSession (laptop/gyro_map.py): tilt -> rover protocol message
   |  UDP datagram to 127.0.0.1:8766, JSON {"kind": "command", "message": {...}}
   v
Blender (simulation/blender_rover.py, run inside Blender)
   |  SimRover (laptop/sim_rover.py): same messages and arm kinematics as the real rover
   v
3D scene: rover body, wheels, arm, gripper, blocks, heat zone, survivor marker
```

The link is one-way. Nothing goes back to the phone except the WebSocket staying open. Blender does not send state or events anywhere.

## 3. Files

| File | Lines | Role |
|---|---|---|
| `simulation/phone_control.html` | 170 | The phone page. Reads tilt sensors, has Drive and Arm tabs, an elbow slider and gripper button (shown only in Arm mode), Centre tilt and STOP. |
| `simulation/phone_bridge.py` | 109 | FastAPI app. Serves the page, a health check, and the WebSocket. Turns samples into messages and forwards them over UDP. |
| `simulation/blender_rover.py` | 225 | Runs inside Blender. Builds the scene, listens on UDP, steps `SimRover`, moves the 3D objects. |
| `simulation/test_phone_bridge.py` | 191 | 23 tests for the bridge (messages, mode-change stop, stale-phone stop, bad input never moving the rover, the stop on every kind of exit, the page's structure, origin rule, WebSocket). |
| `laptop/gyro_map.py` | 121 | Pure logic: tilt angles to `drive` and `arm_pose` messages. No network, no clock. |
| `laptop/sim_rover.py` | 418 | The software rover: protocol handler, wheel and arm motion, plan runner, sensors. Pure logic with an explicit clock. |
| `laptop/origin_guard.py` | 25 | `origin_allowed(origin)`: which web pages may use the WebSocket. |
| `laptop/models.py` | 48 | Frozen dataclasses `Block`, `HeatZone`, `PlanStep`, `Plan`. |
| `laptop/tests/test_gyro_map.py`, `laptop/tests/test_sim_rover.py` | | 33 and 42 tests for the two logic modules. |

`phone_bridge.py` and `blender_rover.py` add the `laptop/` folder to `sys.path` themselves, so they can import `gyro_map`, `sim_rover`, `models` and `origin_guard` without installing the project. `simulation/` has no `__init__.py`; it works as a namespace package (`simulation.phone_bridge:app`).

## 4. Units and coordinate frames

- Distances are millimetres in all Python code. Angles are degrees. Time is seconds.
- Blender works in metres: `blender_rover.py` multiplies millimetres by `MM = 0.001`.
- **Arm frame and world frame:** x forward, y left, z up. The rover starts at the origin facing +x. `heading` is in radians, 0 along +x, positive turns left (anticlockwise seen from above).
- **Phone angles** (the browser's DeviceOrientation values): `beta` is front/back tilt, `gamma` is left/right tilt, both in degrees. The compass angle `alpha` is deliberately ignored because it drifts on most phones.
- The phone is held flat, screen up. Top edge tilted down = forward. Right edge tilted down = right.

## 5. The phone page and its messages

`phone_control.html` is a single self-contained file (inline CSS and JavaScript, no libraries).

- **Enable phone controls** asks for motion permission where the browser needs it (iOS), opens `ws(s)://<host>/phone`, and starts sending.
- **Sensor source:** it uses `deviceorientation` (beta, gamma). If that event does not arrive for a second it falls back to `devicemotion`, computing pitch and roll from gravity. The page shows which source is active and shows "No tilt samples" after 1.5 s of silence (its hint no longer mentions the Android flag in section 7).
- **Sample sent to the server** (JSON text, one per sensor event, and again whenever the slider or button changes):

```json
{"beta": -12.3, "gamma": 4.0, "mode": "drive", "elbow": -90, "grip": true}
```

  Optional fields: `"calibrate": true` (use the current hold as the centre; sent on the first sample, when the sensor source changes, when the mode changes, and when Centre tilt is pressed) and `"stop": true` (STOP ROVER pressed).
- **Safety on the page:** STOP ROVER sends a stop and disables the page. Hiding the page (switching apps, locking the screen) also stops. Closing the WebSocket shows "rover stopped".
- **Mode, elbow and gripper** come from the screen, not from tilt: Drive and Arm tabs, an elbow slider from -135 to 135 degrees, and an open/closed gripper toggle. The elbow slider and gripper button sit in a panel that is hidden in Drive mode and shown in Arm mode. **Centre tilt** is disabled until the page is connected.
- **Look:** a light, flat "field instrument" theme with large touch targets, safe-area padding for phone notches and a reduced-motion setting. It is one self-contained file. Its stylesheet still contains an older dark theme that the light theme overrides.

## 6. Tilt to command: `laptop/gyro_map.py`

`GyroSession` is one phone. Its `update(sample, now)` returns a list of protocol messages.

Constants: full output at a 30 degree tilt (`TILT_FULL_DEG`), 4 degree dead zone (`DEADZONE_DEG`), smoothing factor 0.35 (`SMOOTHING`, higher follows the phone faster), a phone is stale after 0.5 s (`STALE_AFTER_S`).

- The first sample, or any sample with `calibrate`, sets the centre. Tilt is measured relative to that centre after smoothing, so a sudden tilt reaches full output over several samples (one sample gives about a third).
- `axis(delta)` maps a tilt to -1..1 with the dead zone.
- **Drive mode:** `throttle = -axis(d_beta)`, `steer = axis(d_gamma)`, `left = throttle + steer`, `right = throttle - steer`, then both are divided by the larger magnitude if it exceeds 1. Output: `{"type": "drive", "left": L, "right": R}` with L and R in -1..1, rounded to 3 places.
- **Arm mode:** `base = -axis(d_gamma) * 90`, `shoulder = 60 + axis(d_beta) * 60`, `elbow` and `gripper` from the screen (gripper open = 90, closed = 0). Output: `{"type": "arm_pose", "base": .., "shoulder": .., "elbow": .., "gripper": .., "speed": 1.0}`, rounded to 2 places.
- A `stop` sample returns one zero-speed `drive` message.
- A mode change returns two messages: a zero-speed `drive`, then the first message of the new mode (see the limitations in section 10).
- A sample is checked in full before anything is remembered: if `beta`, `gamma` or `elbow` is missing, not a number, `NaN` or infinite, the whole sample is ignored (`[]`) and the session's mode, centre, smoothing and "phone is alive" clock are left as they were. This matters because Python's JSON reader accepts `NaN` and `Infinity`, which would otherwise become full-speed motion. An unknown `mode` keeps the current one.
- `idle(now)` returns one zero-speed drive message when no sample has arrived for 0.5 s, then stays quiet until the next sample. The bridge calls it (section 7).

The messages match `docs/protocol.md` (`drive`: `left`, `right` in -1..1; `arm_pose`: `base`, `shoulder`, `elbow`, `gripper` in degrees, `speed` 0..1).

## 7. The bridge: `simulation/phone_bridge.py`

Start it from the repository root so `simulation.phone_bridge` can be imported:

```
laptop/.venv/Scripts/python -m uvicorn simulation.phone_bridge:app --host 0.0.0.0 --port 8765
```

| Route | What it does |
|---|---|
| `GET /` | Serves `phone_control.html`. |
| `GET /health` | `{"ok": true, "blender_udp": "127.0.0.1:8766"}`. |
| `WS /phone` | One `PhoneBridge` (and so one `GyroSession`) per connection. Each text frame is parsed as JSON (invalid JSON is skipped), passed through the session, and the result is sent to Blender. |

- **What is forwarded:** `PhoneBridge.handle_all` returns one `{"kind": "command", "message": ...}` packet for every message the session produced, so a mode change keeps its zero-speed `drive` before the first arm command. Each packet is sent as its own UDP datagram to `127.0.0.1:8766`. `PhoneBridge.handle` is kept for older callers and returns only the final packet, or `None`.
- **Phone gone quiet:** the WebSocket loop waits at most 0.1 s for a sample. On each timeout it calls `PhoneBridge.idle`, which sends one zero-speed `drive` once the phone has been silent for 0.5 s and then stays quiet until the next sample.
- **Fail closed:** whatever ends a WebSocket connection (the phone leaving, unreadable data, or a crash in the handler), the bridge sends one zero-speed `drive` command to Blender before it closes its socket. A sample that cannot be read (bad JSON, wrong type, bad numbers) is skipped and never reaches the rover, and the connection stays open.
- **Origin rule** (`origin_allowed`): the WebSocket is refused with close code 1008 unless the `Origin` header is missing (scripts) or its host is `localhost`, a loopback address, a private LAN address or a link-local address. This stops a web page on the public internet from driving the rover through a visitor's browser. It is not authentication: any device on the same network that sends no `Origin` header, or a local one, can connect.
- **Plain http on purpose.** Browsers treat plain-http pages as insecure, which limits motion sensors: on Chrome for Android the flag `chrome://flags/#unsafely-treat-insecure-origin-as-secure` must be set to the page's address; iOS Safari requires a secure page for motion permission, so an iPhone is not expected to work over http. There is no HTTPS or certificate setup in the repository any more.

## 8. The rover model: `laptop/sim_rover.py`

`SimRover(blocks=(), heat_zones=(), survivor=None)` is the same class the operator server uses. Drive it with `handle(message)` (returns the messages the rover would send back) and `step(dt)` (advances time, returns periodic messages). The phone path uses only `drive` and `arm_pose`; it also understands `ping`, `mode`, `plan`, `plan_start` and `abort`, and ignores unknown types.

**Geometry (all assumptions until the real arm is measured):** arm base height 60 mm, two links of 105 mm each, wheel base 140 mm (unmeasured; the buggy is officially 200 mm wide overall, so the real wheel base is under 200 mm), top speed 200 mm/s, block size 40 mm.

**Wheels:** `drive` sets left and right speed (each clamped to -1..1). Each step: `forward = (left + right) / 2 * 200 mm/s`, `turn = (right - left) * 200 / 140 rad/s` (positive turns left), then heading and position are integrated. Drive commands are ignored while a stored plan is running.

**Arm:** `arm_pose` sets a target, clamped to the joint limits (base -90..90, shoulder 0..120, elbow -135..135, gripper 0..90 where 0 is closed and 90 is open). `speed` is clamped to 0.05..1. Each joint moves toward its target at 120 degrees per second times `speed`. Home pose: base 0, shoulder 60, elbow -90, gripper 90. `arm_tip(pose)` gives the tip position (forward kinematics) and `solve_pose(x, y, z, gripper)` gives joint angles for a tip position (elbow up), or `None` if unreachable.

**Link timeout:** if no `ping` arrives for 2 s, `step` emits a `link_lost` event once and, if no plan is running, stops the wheels and freezes the arm target.

**Blocks:** `WorldBlock(block, z)`; every block starts with its centre 20 mm above the ground. Blocks only move when a stored plan carries them (`pick` and `drop` steps). **The phone cannot pick up blocks**, because it can only send `drive` and `arm_pose`. It can drive and pose the arm and show the gripper opening.

**Reports:** `state_message()` (5 Hz in `step`), `sensors_message()` (2 Hz: IR obstacle left/right, IR flame left/right, DHT readings, battery volts) and `snapshot()` (rover pose, arm joints, tip, blocks, heat zones, survivor, link state) exist. Blender only uses `snapshot()`.

## 9. The Blender scene: `simulation/blender_rover.py`

Start Blender with this file as the script (Blender must be installed separately; the script imports `bpy`, which is not available in the project's Python environment):

```
blender --python simulation/blender_rover.py
```

At start it clears the scene, builds the objects below, binds UDP `127.0.0.1:8766` (non-blocking) and registers a timer that runs every 1/60 s. Each tick: measure elapsed time (capped at 0.1 s), read every waiting UDP datagram, step `SimRover`, then move the objects.

- **Packets:** UTF-8 JSON. Only `{"kind": "command", "message": {...}}` is acted on, by calling `SimRover.handle(message)`. Anything unreadable is ignored. Messages the rover would send back are discarded.
- **Demo world (hard-coded):** blocks 1 (170, 0) bottom layer, 2 (170, 0) top layer, both light; block 3 (125, -120) bottom layer, heavy; a heat zone at (125, 130) with radius 40 mm; the survivor at (300, 0). Positions are millimetres in the world frame.
- **Objects:** `Ground`, `RoverBody` (0.24 x 0.18 x 0.07 m), four `Wheel`s, `ArmBase`, `ShoulderPivot`, `UpperArm`, `ElbowPivot`, `Forearm`, `Gripper`, `LeftFinger`, `RightFinger`, `Block_<id>` (40 mm cubes), `HeatZone`, `Survivor`, an area light and a camera. Colours come from the `SCENE_COLORS` table (white body, green arm, yellow wheels, red claw, black blocks, grey ground).
- **State to objects each tick:** body location is the rover's x, y (millimetres to metres) and its z rotation is the heading; `ArmBase` rotates about z by the base angle; `ShoulderPivot` and `ElbowPivot` rotate about y by the negated shoulder and elbow angles (radians); finger y offsets are +/- `(8 + gripper * 0.25)` mm converted to metres; each block takes the position and height from `snapshot()`.
- **Viewport:** the script frames a perspective view of the rover in solid shading on start.

## 10. Known limitations (verified in this repository)

1. **The link-loss safety in the rover model is not active.** The bridge never sends `ping`, so the twin's `SimRover` reports `link_lost` about 2 s after Blender starts and stays in that state. Driving still works, but after that first trip the rover model's own "stop the wheels after 2 s of silence" rule never fires again. The bridge's own stale-phone stop (section 7) covers the phone going quiet, so this only matters if the bridge itself dies.
2. **No feedback to the phone.** Blender never reports state, so the page cannot show where the rover is.
3. **Block layers are ignored by the physics.** Blocks 1 and 2 share the same x, y and both sit 20 mm up, so the stack overlaps instead of stacking. `layer` is only data for the planner.
4. **Blender dimensions are approximate, and one is wrong for the official size.** The buggy is officially 200 mm wide overall (450 to 500 mm long), but the Blender wheels sit 105 mm either side of the body centre, a 210 mm track that is wider than the whole buggy, while the motion model uses a 140 mm wheel base. Neither number is measured. Measure the real wheel track and set both to it. The arm and body sizes are rough too.
5. **Blender is not covered by automated tests**, because `bpy` cannot be imported in the test environment. The tilt mapping, the rover model and the bridge are.
6. **The bridge is not authenticated.** Run it only on a network you trust.
7. **Assumed numbers:** every geometry, speed and servo value in section 8 is an assumption until the real rover is measured.

## 11. Running and testing

- **Install:** the project virtual environment (`laptop/.venv`, Python 3.13) already has FastAPI and uvicorn. Tests also need the `dev` extra (`pytest`, `pytest-cov`, `httpx2`).
- **Run order:** start Blender with the script, then start the bridge, then open `http://<laptop-ip>:8765/` on the phone (same Wi-Fi), press Enable phone controls and hold the phone still so it centres.
- **Tests:** from the `simulation/` folder, `../laptop/.venv/Scripts/python -m pytest -q` runs the 23 bridge tests. From `laptop/`, `.venv/Scripts/python -m pytest -q test_gyro_map.py test_sim_rover.py` runs the logic tests. From the repository root, `pytest` runs everything.
- **Bridge tests cover:** the page's structure (arm controls hidden in Drive mode, tabs, safe-area and reduced-motion rules), a smoothed drive command after calibration, the arm message shape, bad input, the stop kept before the arm command on a mode change, the single stop after the phone goes stale, the origin rule for allowed and refused pages, a refused and an accepted WebSocket, and the page being served over http.

## 12. Where to change things

| To change | Edit |
|---|---|
| Tilt feel (dead zone, full tilt angle, smoothing, arm ranges) | constants at the top of `laptop/gyro_map.py`, then update `test_gyro_map.py` |
| Which messages reach Blender | `PhoneBridge.handle` in `simulation/phone_bridge.py` |
| What the phone page shows or sends | `simulation/phone_control.html` |
| Rover speeds, arm lengths, joint limits | constants at the top of `laptop/sim_rover.py` (shared with the operator server) |
| The demo world or the look of the scene | `BlenderTwin.__init__`, `create_scene` and `SCENE_COLORS` in `simulation/blender_rover.py` |
| Ports | `BLENDER_PORT` in `phone_bridge.py` and `UDP_PORT` in `blender_rover.py` must match (8766), and the uvicorn `--port` (8765) |
| Who may connect | `laptop/origin_guard.py` (the operator server uses the same rule) |

Messages sent to the real rover are defined in `docs/protocol.md`. Change that file only when all four team members agree.
