# Production readiness

Written on 20 October 2026 after a full review of the repository. It lists what was fixed, what is still open and who has to decide it. Nothing here has been tested on a real rover: the hardware gate in `docs/trials.csv` is still open, see `docs/mission-9-compliance.md`.

## Fixed in this review

| Area | Problem | Fix |
|---|---|---|
| Safety | A stop (abort, scene change, plan not confirmed) that could not be delivered because the Wi-Fi was down was forgotten, so the page said "Stopped" while the rover kept running its stored plan | The operator now asks again on every tick until the rover receives it (`operator_core.py`) |
| Stability | One malformed message from the rover (a step report with no step number) raised an exception in the thread that services the rover and stopped it | Malformed messages are ignored (`operator_core.py`) |
| Stability | Any unexpected exception in the rover link thread, the rover loop or the camera loop ended that thread silently | They are logged and the loop carries on (`rover_link.py`, `server.py`) |
| Safety | Plan ids came from the time since the laptop booted, so a restart could reuse an id the rover still held | They come from the calendar clock (`operator_core.py`) |
| Security | A web page on the internet could point its own name at this laptop (DNS rebinding) and read the operator state | Requests whose Host header is a public name are refused (`origin_guard.py`, `server.py`) |
| Security | The arm board's fallback Wi-Fi password was the public default `12345678` | It is now set in `firmware/secrets.h` as `ARM_AP_PASSWORD` (`rover_arm_ap.cpp`, `secrets.example.h`) |
| Packaging | `pip install .` left out five modules the server imports, so the installed server could not start | Listed in `pyproject.toml`, with a test so it cannot drift again (`test_packaging.py`) |
| Build | `npm run typecheck` failed under the strict settings (array lookups that might be undefined) | Fixed in `control.ts` and `ui_logic.ts`; the built `.js` is regenerated |
| Pages | A server refusal on the operator page showed "Not connected" instead of the reason, and polls could overlap | The page shows the server's own message, one poll at a time (`operator.ts`) |
| Privacy page | Said the control page was "not connected to anything yet" and did not mention the access cookie | Updated, with today's date (`privacy.html`, `terms.html`) |

## Open: must be decided before real use

### 1. The rover's network ports have no authentication (high)

- **Command port 81** (`firmware/rover_link.cpp`) only checks the browser `Origin` header. A program that sends no Origin (any script on the same Wi-Fi) can connect, take the single operator slot and drive.
- **Arm board** (`firmware/rover_arm_ap.cpp`) answers `/drive`, `/servo` and `/home` to anyone, and sends `Access-Control-Allow-Origin: *`. A plain `<img src="http://still-arm.local/drive?d=F&v=255">` on any web page open on the operator's phone moves the rover; CORS does not stop a GET from being sent.
- **Video** (`/stream`) is open to the whole network.

Suggested fix, done together on both sides so it can be tested on the bench: a long random token in `secrets.h`, required as a header (command port) or a parameter (arm board and video), and sent by `rover_link.py` and `control.ts` from `config.toml`. Remove the wildcard CORS header. Until then run only on a phone hotspot with a strong password and no other devices.

### 2. A stale operator connection blocks a new one (medium)

`rover_link.cpp` refuses a second operator while the first is registered. After a Wi-Fi blip the old connection can stay registered for up to about 21 seconds (the heartbeat settings), so the laptop cannot reconnect until it expires. Let a new connection from an allowed origin replace the old one. Needs a bench test, because the link-loss behaviour in `rover_core.h` depends on the order of the events.

### 3. Hardware is unproven (high)

The 8 of 10 two-block benchmark, joint directions, IR polarity, wheel track and battery reading are all open (`docs/demo-assumptions.md`, `docs/bench-and-integration-checklist.md`). The two firmware variants also describe different arms (4 servos on the ESP32-S3, 5 servos on the classic ESP32). Pick one as the final robot.

### 4. Operations (medium)

- **No continuous integration.** Add a workflow that runs `pytest`, `npm run typecheck`, `npm test` and the C++ host tests (`ctest`) on every push. The pieces all run locally today.
- **No LICENSE file.** Without one, the code is "all rights reserved" by default and no one else may legally use it. The terms page says as much. The team must choose a licence (MIT or Apache-2.0 are the usual choices for a student project).
- **Dependencies are lower bounds only** (`>=`). Pin exact versions with a lock file before deploying, so a new release cannot change behaviour.
- **The person detector model** is not in git (9 MB). Keep its SHA-256 in `docs/survivor-detection.md` and check it on load.
- **Logging** goes to the console only. Redirect it to a file if the server runs unattended.

### 5. Privacy (low)

The public pages load the Hanken Grotesk font from Google Fonts, which sends visitors' IP addresses to Google (the privacy page says so). Self-hosting the font removes that and makes the "collects nothing" claim simpler.

### 6. Perception limits (medium)

- The person detector is not used by the operator page and does not recognise the Blender figure (`docs/survivor-detection.md`).
- Colour thresholds in `vision.py` are tuned for the demo lighting. Expect to retune them for a new room.
