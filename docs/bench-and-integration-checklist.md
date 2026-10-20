# Bench and integration checklist

This is the execution order for the real rover. It does not replace
`docs/protocol.md`; that document remains the agreed laptop-to-rover contract.

## Safety before every test

- Put the wheels off the ground for all first runs.
- Hold the arm clear of the chassis and people.
- Keep one hand on the power switch and the abort button reachable.
- Use the two-supply system in `power.md` before operating wheels and servos together.
- Never power servos from the ESP32 3.3 V rail. The PCA9685 needs 3.3 V on `VCC`
  for logic and its own 5–6 V servo supply on `V+`; all grounds must be common.

## 1. Bench test

`firmware/sketches/bringup.txt` is an Arduino IDE diagnostic sketch, not a PowerShell
command and not a PlatformIO source file. Paste it into an Arduino sketch named
`bringup`, upload it, then open Serial Monitor at 115200 baud with `Newline`.

The first required check is:

```text
scan
```

It must print `device at 0x40  <- servo driver`. The PCA9685 is on GPIO 39
(`SDA`) and GPIO 40 (`SCL`) using `Wire`. `Wire1` is reserved by the camera;
using it causes a false “not found” result.

Then, with the arm clear, test the gripper first at a safe centre angle:

```text
servo 3 90
servo 3 80
servo 3 100
off
```

Only after recording the physical channel and direction for every joint should
`SERVOS[]` in `firmware/hardware.cpp` be changed. Do not assume a direction or
centre pulse from the simulation. Keep the elbow inside its confirmed protocol
range of -135 to +135 degrees in `firmware/rover_arm.h`.

Test wheels one side at a time:

```text
motor L f
motor R f
```

If a side is physically backward, swap only that side's `IN1` and `IN2` values
in both `firmware/pins.h` and `firmware/sketches/bringup.txt`, then repeat the test.

Run `sensors` and `batt` last. The left/right obstacle sensors are currently
unwired (`-1`), so the sketch reports `-1` for them. Do not turn on
`IR_OBSTACLE_STOP_ENABLED` or alter `readActiveLow()` until real readings have
been recorded. Do not enable `BATTERY_DIVIDER_FITTED` until `batt` agrees with
a multimeter.

Record the result before changing production constants:

| Item | Observed result | Firmware change needed |
|---|---|---|
| PCA9685 address | | |
| Base / shoulder / elbow / gripper channel | | `SERVOS[]` |
| Positive direction for each joint | | `SERVOS[].direction` |
| Left / right forward direction | | `pins.h` IN1/IN2 if needed |
| IR clear / blocked logic level | | `readActiveLow()` if needed |
| Multimeter / `batt` voltage | | `BATTERY_DIVIDER_FITTED` if validated |

## 2. Real firmware and Wi-Fi

Copy `firmware/secrets.example.h` to `firmware/secrets.h` and enter a 2.4 GHz
network name and password. That file is intentionally git-ignored.

From `still-here/firmware`:

```powershell
python -m platformio run -e esp32s3 -t upload
python -m platformio device monitor -b 115200
```

The board prints its IP address. From the laptop, try:

```powershell
ping still-here.local
```

If mDNS does not resolve, use the printed IP address instead. Open
`http://still-here.local/stream` or `http://<rover-ip>/stream` to confirm the
camera before attempting motion.

## 3. Link, then manual control

From the `still-here\laptop` folder, use its virtual environment:

```powershell
.venv\Scripts\python.exe ..\firmware\rover_control.py --rover still-here.local
```

Replace `still-here.local` with the rover IP if required. Keep the wheels off
the ground. Closing the console must stop the rover within two seconds.

## 4. Full operator server

From `still-here/laptop`:

```powershell
.venv\Scripts\python.exe server.py --rover still-here.local
```

Check `/api/state` reports `rover_connected: true`. Start with one stored plan
while the rover is stationary. Verify `plan_stored`, `step_done`, and
`plan_finished`. Test link loss only with a safe, stationary arrangement and
after the team accepts the clarifications in `protocol.md`.

## 5. Calibration and the gate

Do not replace the assumed `WHEEL_BASE = 140.0` or `MAX_SPEED_MM_S = 200.0`
in `laptop/sim_rover.py` until measured. Record measurements first, then update
the simulation and Blender twin together. Print markers, calibrate the table,
and run `trial_log.py` for all ten two-block tests. The gate is at least eight
passes, with the bottom block moving under 5 mm and 10 degrees.
