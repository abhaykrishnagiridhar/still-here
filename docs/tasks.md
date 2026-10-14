# Task split

Four people, one owner per area. The gate comes first: nothing from Stage 2 or 3 starts until the two-block test passes 8 of 10.

| Person | Owns | Files |
|---|---|---|
| A, Perception | Find the light, the blocks, their layer order | `laptop/perception.py` |
| B, Planner and UI | Pick order, web UI, trial logger, final report | `laptop/planner.py`, `laptop/server.py`, `laptop/models.py` |
| C, Firmware | Camera stream, WebSocket server, arm, wheels, sensors | everything in `firmware/` |
| D, Hardware and tests | Build, power, calibration, run the 10 trials | `docs/trials.csv`, calibration script |

## H0 to H2 (everyone)

- [ ] Read `docs/protocol.md`, raise changes now
- [ ] Agree pin map, servo roles and block size, and fill in `firmware/pins.h`
- [ ] Each person clones, runs the quick start in the README

## A, Perception

- [ ] Detect the pulsing light from the webcam (brightness varying over time)
- [ ] Detect ArUco markers on blocks, return position and id
- [ ] Decide layer from marker visibility and vertical position in the image
- [ ] Tests on saved frames

## B, Planner and UI

- [ ] Planner: top blocks first, supporting blocks untouched, unit tested
- [ ] FastAPI server and TypeScript UI showing the feed, blocks and plan
- [ ] Trial logger writing to `docs/trials.csv`

## C, Firmware

- [ ] Camera stream and WebSocket server
- [ ] PCA9685 driver with speed limits, `pick` and `drop`
- [ ] Plan buffer, link-loss behaviour, safe stop
- [ ] Sensor readout (IR obstacle, IR flame, DHT11)

## D, Hardware and tests

- [ ] Build the two-supply power system in `docs/power.md` (power bank for logic, 18650 pack for motors and servos) and pass its test plan
- [ ] Decide what to do about the "500 series" motor (see Open items in `docs/power.md`)
- [ ] Calibration: camera pixels to arm frame, one command to re-run
- [ ] Print markers, make blocks (40 mm cubes), one heavy block
- [ ] Run and log the 10 trials

## Later, only after the gate passes

Tap-to-select, re-plan on a shifted block, heavy-block skip, finish plan on link drop, IR stop and mode switch, heat layer, final report and one chime.
