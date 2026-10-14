# STILL HERE

A rescue rover that clears a safe path to a trapped survivor (a pulsing light in a dim room).
Built for Innovation Mission 9, "Intelligent Robotics: Autonomous Object Interaction" (48 hours).

## How it works

- **Rover (ESP32-S3)** streams camera video and executes commands: 4-servo arm through a PCA9685, wheels through an L298N, IR and DHT11 sensors.
- **Laptop** finds the light and the blocks, plans which block to remove first, and shows everything in a web UI.
- The two talk over Wi-Fi (phone hotspot, 2.4 GHz) using the messages in `docs/protocol.md`.

## Folders

| Folder | Contents |
|---|---|
| `laptop/` | Python code: vision, planner, API server, shared data models |
| `firmware/` | ESP32-S3 code (PlatformIO) |
| `docs/` | Protocol, task split, trial log, the original brief |

## The one thing to do first

The **two-block stack test**: on a two-layer stack the camera finds both blocks, software picks the top one, and the clamp removes it without disturbing the other. Run it 10 times and log each run in `docs/trials.csv`. If fewer than 8 pass, fix grip padding, block weight and camera placement, in that order, before any other feature.

Pass rule: the bottom block moves less than 5 mm and rotates less than 10 degrees (measured from its marker before and after).

## Team rules

- `docs/protocol.md` is the contract between laptop and firmware. Change it only when all four agree.
- Each person edits their own files (see `docs/tasks.md`). Ask before touching someone else's.
- Never commit `firmware/secrets.h` or `laptop/config.toml`. Copy the `.example` files instead.
- Units: millimetres and degrees everywhere.

## Quick start

Laptop:

```bash
cd laptop
python -m venv .venv
.venv/Scripts/activate        # Windows
pip install -e ".[dev]"
pytest
```

Firmware: install PlatformIO, copy `firmware/secrets.example.h` to `firmware/secrets.h`, fill in `firmware/pins.h`, then `pio run -d firmware`.
