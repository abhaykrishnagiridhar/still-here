# The autonomous loop in the Blender twin

This runs the whole loop, with the real laptop code, against a simulated rover and table in Blender:

1. **See.** The server's own vision reads pictures from a top-down camera in Blender: red blocks, an orange fire pad, and the survivor's pulsing light.
2. **Plan.** The real planner and route finder choose which blocks to remove and which to leave, and why.
3. **Approve.** A human presses Approve on the operator page. Nothing moves before that.
4. **Run.** The plan goes to the Blender rover over the same messages the real rover uses (`docs/protocol.md`).
5. **Check.** The camera must see the way clear in three pictures in a row. Then the report is written.

If the scene changes during the run, the rover stops and a fresh plan is offered, as with the real one.

## Autonomous and learning: the same course, run again

With `--auto` the laptop approves its own plans and runs the course several times, and the rover's behaviour improves from one run to the next. This is the part of the brief about adapting to unexpected situations and improving.

The twin hides one fact from the planner: the buggy is really a little wider than it was told (`BUGGY_TRUE_HALF_WIDTH_MM` in `laptop/demo_world.py`).

| Run | What happens |
|---|---|
| 1 | The planner removes the four blocks across the path and leaves the fifth, which it believes is clear of the buggy. On the drive to the survivor the buggy brushes it. The rover reports a `bump`. |
| learning | `laptop/experience.py` records the run as one that had trouble and widens the corridor by 10 mm each side. The page says so, and the Blender board shows the new width. |
| 2 | The course is reset. The planner now counts the fifth block as in the way and removes it too: five blocks moved, nothing touched, camera confirms the way is clear. |
| 3 and later | The same, with the same corridor. It has stopped needing to learn. |

Nothing in this is scripted. The first run goes wrong because the physics says it should, and the second goes right because of what the laptop stored. `laptop/tests/test_learning_loop.py` proves it with no Blender at all.

What you see in Blender: green rails mark the corridor the planner keeps clear (they move apart when it widens), a board in front of the rover shows the run number and what was learned, and a pink pad marks the block that was brushed. The top-down camera never sees any of these, so the vision code is not disturbed.

Safety stays: autonomous mode exists only against the Blender twin (the server refuses `--auto` with a real rover). It waits 2.5 seconds on each plan before approving and approves only a plan that stayed unchanged for that time. Pressing **Stop the rover** switches it off for good, until the server is started again.

## What is simulated, and what is not

- Real: the vision, the planner, the approval step, the operator page, the message protocol, the camera check, the report.
- Simulated: the rover and its arm (`laptop/sim_rover.py`, drawn by `simulation/blender_rover.py`), and the camera pictures (rendered by Blender).
- Not proven by this: the physical arm, the real camera, or the 8 of 10 two-block benchmark.

## Run it

Close any Blender that already has the twin open (it holds UDP port 8766), then:

```powershell
blender --python simulation\blender_rover.py
```

In another window, from `still-here\laptop`:

```powershell
.venv\Scripts\python.exe server.py --blender 8766
```

Open http://127.0.0.1:8000/ . The survivor's light is found on its own after a couple of seconds. Read the plan, then press **Approve plan**.

For the autonomous, learning version, start the server like this instead and just watch (it starts untrained every time, so the first run always shows the mistake; add `--remember` to keep what past runs taught):

```powershell
.venv\Scripts\python.exe server.py --blender 8766 --auto --episodes 3
```

The page lists each finished run under **Learning across runs**.

To use a different port, set `STILL_HERE_UDP_PORT` before starting Blender and pass the same number to `--blender`.

## Record a video

With both of the above running and the scene untouched (restart Blender for a fresh scene). In autonomous mode the recorder does not click anything: it records until the last run ends and adds a card listing what each run taught the laptop.

```powershell
.venv\Scripts\python.exe ..\simulation\record_demo.py --server http://127.0.0.1:8000 --blender-port 8766
```

It plays the human: it waits for the plan, shows it for 6 seconds, then approves it, and approves a fresh plan again if a safety stop happens. The video is written to `simulation\frames\autonomy_demo.mp4`. Every frame comes from the running system.

## The demo world

`laptop/demo_world.py` holds it: four blocks across the path, one block off to the side, a fire pad, the survivor 300 mm ahead. Blender and the tests both read it. The route and plan on this world are checked in `laptop/tests/test_demo_world.py`.

Blocks are put down in four slots outside the corridor (`DROP_SLOTS_MM` in `laptop/operator_core.py`), so the camera never sees a dropped block in the way.

## Things to know

- The top-down picture is rendered with anti-aliasing off so Blender gives about 12 pictures a second. The survivor-light finder needs 8 pictures in 1.5 seconds.
- The fire keep-out radius is 45 mm for this demo (`HEAT_RADIUS_MM` in `demo_world.py`), because the project's default 100 mm is meant for a real fire and would fill a 427 mm wide table.
- Tested headless (`blender -b`). The Blender window runs the same script.
