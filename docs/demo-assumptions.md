# Time-boxed demo assumptions

The wiring checks in `bench-and-integration-checklist.md` must be done and recorded first. There is not enough time for a
per-servo pulse calibration or the ten-run two-block benchmark, so the project
uses the following conservative, explicitly approximate demo profile.

| Item | Demo setting | Source |
|---|---|---|
| PCA9685 I2C address | `0x40` | Bench scan / standard PCA9685 address |
| PCA9685 bus | `Wire`, GPIO 39 SDA and GPIO 40 SCL | `firmware/pins.h` |
| Servo channels | base 0, shoulder 1, elbow 2, gripper 3 | `firmware/pins.h` |
| Servo centres | 1500 microseconds | `firmware/hardware.cpp` |
| Standard-servo pulse range | 600–2400 microseconds | `firmware/hardware.cpp` |
| Elbow pulse range | 500–2500 microseconds | `firmware/hardware.cpp` |
| Joint directions | `+1` for every joint | `firmware/hardware.cpp`; revise only if a demo movement is visibly reversed |
| Arm limits | base ±90°, shoulder 0–120°, elbow ±135°, gripper 0–90° | `firmware/rover_arm.h` |
| Wheel direction | existing `pins.h` mapping | Keep wheels off ground for first command after every flash |
| IR polarity | active-low (`LOW` means triggered) | `hardware.cpp` |
| Battery divider | disabled | `BATTERY_DIVIDER_FITTED = false` until multimeter validation |

## Demo limits

- The rover is a demonstration prototype, not an autonomous rescue device.
- Keep wheels off the ground for the first post-flash drive command.
- Do not command a servo near a mechanical end stop. Use the red/abort stop immediately if a joint moves the wrong way.
- The two-block 8/10 result is **deferred**, not passed. Do not claim that it was achieved.
- The right flame sensor and DHT11 are intentionally unavailable and report `null`.

## First live demonstration

1. Flash the real firmware with a local `firmware/secrets.h`.
2. Confirm the camera stream loads.
3. Confirm `rover_connected` from the laptop server.
4. With wheels raised, send one low-speed manual drive command and one gripper command.
5. Run one short approved plan only if the arm and wheel checks are normal.
