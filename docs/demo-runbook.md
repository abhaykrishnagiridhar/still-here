# Demo runbook: real camera, software rover

Use this when the arm and wheels are not ready. The laptop does all of its real work (camera, plan, approval, verification, report). The rover is the software rover that ships with the project, so nothing moves on the table. The person presenting lifts the blocks off by hand as the plan picks them, and the camera then verifies that.

## What you need

- A webcam on the laptop, looking at the table from above or at a steep angle.
- 3 to 5 red cubes about 40 mm wide (or blocks with the ArUco markers from `marker_sheet.py`).
- A pulsing light for the survivor: a blinking LED, or a phone with a flashing light app. If the page cannot find it, tap it in the picture.
- Optional: a small orange object as fire.

## Start

From `still-here\laptop`:

```powershell
.venv\Scripts\python.exe server.py --simulate
```

Open http://127.0.0.1:8000/ . If an older server is still running on port 8000, close it first, or add `--port 8001` and use that address.

## Steps

1. Put the cubes on the table so some of them sit between the rover's spot (bottom centre of the picture) and the survivor light. Wait for the page to say how many blocks it sees.
2. If the page says "Survivor not found", tap the light in the picture.
3. Read the plan aloud: the blocks to remove, in order, and the blocks left in place with the reason.
4. Press **Approve plan**. The progress bar moves as the software rover works through the steps.
5. As each block is picked (the page shows "N of M steps done"), lift that cube off the table by hand and set it aside.
6. When the page says the rover finished, the camera checks the way is clear. It must see a clear path in 3 pictures in a row within 8 seconds. Keep your hands out of the picture.
7. The page shows "done" and the report appears. One chime plays.

To show the safety behaviour, move a block that is not in the plan while the rover runs. The server stops the run, writes it up as a safe stop, and offers a fresh plan.

## What to say

- The perception, the planning, the human approval and the camera check are running live on real pictures.
- The rover in this demo is a software model of the rover protocol. The wheels and arm were not driven.
- The report lists only facts the system recorded. Its summary uses a fixed set of sentences.

## What not to claim

- Do not say the two-block benchmark passed. It has not been run (the gate is 8 of 10).
- Do not say the arm or wheels were calibrated or driven.
- Do not describe the software rover as the physical robot.

## If something goes wrong

| Problem | Fix |
|---|---|
| Camera error or a black picture | Close other programs using the webcam. Try `server.py 1 --simulate` for a second camera. |
| Blocks not found | Use red, matte cubes under even light. Check the picture on the page: the blocks should look solidly red. |
| The plan keeps changing | A block is being nudged. Keep the table still until you approve. |
| "unverified" at the end | A block was still in view. Remove it and start a new run. |
