# Task split

Four people, one owner per area. The gate comes first: nothing from Stage 2 or 3 starts until the two-block test passes 8 of 10.

`[x]` means the software is written and tested. Anything that also needs the real camera, board or arm is marked "needs hardware" and stays open until it has been done there.

| Person | Owns | Files |
|---|---|---|
| A, Perception and operator pages | Find the light, the blocks, their layer order; the pages the operator uses | `laptop/vision.py`, `aruco.py`, `scale.py`, `scene.py`, `scene_watch.py`, `stream.py`, `server.py`, `operator_core.py`, `manual_core.py`, `*.ts` |
| B, Planner, report and trials | Pick order, route, run report, trial logger | `laptop/planner.py`, `route.py`, `models.py`, `plan_message.py`, `report.py`, `trial_log.py` |
| C, Firmware | Camera stream, WebSocket server, arm, wheels, sensors | everything in `firmware/` |
| D, Hardware and tests | Build, power, calibration, run the 10 trials | `docs/trials.csv`, `laptop/calibrate.py`, `marker_sheet.py` |

## H0 to H2 (everyone)

- [ ] Read `docs/protocol.md`, raise changes now, and settle the proposed clarifications at the end of it
- [ ] Agree pin map, servo roles and block size, and fill in `firmware/pins.h` (camera pins are confirmed, the rest is untested)
- [ ] Each person clones, runs the quick start in the README

## A, Perception and operator pages

- [x] Detect the pulsing light (brightness varying over time). Needs hardware: try it on the real camera and choose the light's colour
- [x] Detect ArUco markers on blocks, return position and id
- [x] Decide layer and weight from the marker id (`top_marker_ids`, `heavy_marker_ids` in `config.toml`)
- [x] Operator pages: live picture with the plan drawn on it, tap the survivor, approve, abort, report, manual drive and arm
- [x] Stop the rover and offer a fresh plan if the scene changes mid-run
- [ ] Tests on saved frames. Needs hardware: save real frames and add tests from them
- [ ] Tune the colour masks with `--masks` on the real camera. Needs hardware

## B, Planner, report and trials

- [x] Planner: top blocks first, supporting blocks untouched, unit tested
- [x] Route: the cheapest way to the survivor, with a corridor as wide as the buggy (200 mm plus clearance)
- [x] FastAPI server and TypeScript pages showing the feed, blocks and plan
- [x] Trial logger writing to `docs/trials.csv` and checking the 8 of 10 gate (`laptop/trial_log.py`)
- [x] Fact-first report with an allowed summary and one chime

## C, Firmware

- [x] Camera stream (`camera.cpp`, `mjpeg_server.cpp`). Needs hardware: confirm the frame rate on the board
- [ ] WebSocket server on port 81 with an origin check, announcing the name `still-here` on the network
- [ ] PCA9685 driver with speed limits, `pick` and `drop`
- [ ] Plan buffer, link-loss behaviour, safe stop
- [ ] Sensor readout (IR obstacle, IR flame, DHT11). The right flame sensor and the DHT11 have no pin yet

## D, Hardware and tests

- [ ] Build the two-supply power system in `docs/power.md` (power bank for logic, 18650 pack for motors and servos) and pass its test plan
- [ ] Decide what to do about the "500 series" motor (see Open items in `docs/power.md`)
- [ ] Calibration: measure the table marks, then `python calibrate.py points.json` (the tool is written)
- [ ] Measure the wheel track and top speed, and set them in `laptop/sim_rover.py` and `simulation/blender_rover.py`
- [ ] Print markers (`python marker_sheet.py`), make blocks (40 mm cubes), one heavy block
- [ ] Run and log the 10 trials with `python trial_log.py add ...`

## Later, only after the gate passes

Done in software: tap-to-select the survivor, re-plan on a shifted block, heavy-block skip, the heat layer in the planner, the final report and one chime, and finishing a plan when the link drops (in the software rover).

Still to do: the same on the real rover (finish a plan on link drop, IR stop and mode switch, the flame sensor feeding the heat layer).
