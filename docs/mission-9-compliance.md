# Innovation Mission 9: how STILL HERE meets the brief

Checked on 20 October 2026 against the challenge text, "Intelligent Robotics: Autonomous Object Interaction". The right-hand columns say where to see the proof. "Sim" means the software rover or the Blender twin, which the brief allows: "Simulation is acceptable where physical robotic hardware is unavailable."

## The brief, line by line

| The brief asks for | What we have | Proof | State |
|---|---|---|---|
| **Problem:** understand the environment before deciding and interacting | Camera first, plan second, nothing moves before a person approves | `laptop/vision.py`, `laptop/operator_core.py` | Met |
| **Build:** a robotic or simulated system that perceives objects, decides, and acts | Rover firmware plus laptop planner, and a full software rover for the same messages | `firmware/`, `laptop/sim_rover.py`, `docs/protocol.md` | Met (sim); hardware not proven |
| **Stage 1: Foundation.** Detect or identify objects with sensors, computer vision or other perception | ArUco markers give each block its id, layer and weight; red-blob fallback; fire by colour; the survivor by its pulsing light; IR obstacle and flame sensors; a pretrained YOLOX-S person detector (OpenCV, no training) | `laptop/aruco.py`, `laptop/vision.py`, `laptop/person_detector.py`, `docs/survivor-detection.md` | Met |
| **Stage 2: Functional solution.** Decide, then perform a physical or simulated action such as sorting, retrieving, transporting or repositioning | Route search picks the cheapest set of blocks to remove, then pick and drop each into its own slot outside the corridor | `laptop/route.py`, `laptop/planner.py`, `laptop/operator_core.py` | Met (sim) |
| **Stage 3: Innovation and intelligence.** Adapt to changing object positions | Every picture is compared with the scene the plan was made for; a moved, vanished or new block stops the rover and offers a fresh plan | `laptop/scene_watch.py`, `laptop/tests/test_operator_replan.py` | Met |
| ...improving from experience | Run the same course again and again (`server.py --blender 8766 --auto`). Run 1 brushes a block the planner thought safe; the laptop learns and widens the corridor; run 2 removes that block too and touches nothing | `laptop/autopilot.py`, `laptop/experience.py`, `laptop/tests/test_learning_loop.py`, `docs/autonomy-demo.md` | Met (sim) |
| ...environmental conditions | Heat zones are avoided; the keep-out radius is configurable; corridor clearance is learned from past runs | `laptop/route.py`, `laptop/experience.py` | Met |
| ...multiple object types | Blocks by layer and weight class (heavy blocks are never lifted), fire, survivor | `laptop/aruco.py`, `laptop/planner.py` | Met |
| ...unexpected situations | Link loss (rover finishes the stored plan alone), failed grip check, IR obstacle stop, rover not confirming a plan, camera lost, and a stop that could not be delivered is sent again | `laptop/grip_watch.py`, `laptop/operator_core.py`, `laptop/rover_link.py`, `firmware/rover_core.h` | Met (sim) |
| ...autonomous operation | In `--auto` mode the laptop approves its own plans and resets the course between runs. A person pressing Stop takes over for good. The real rover is never run this way | `laptop/autopilot.py` | Met (sim only, on purpose) |
| **Minimum deliverable.** Successful perception followed by an appropriate physical or simulated interaction | The camera sees the scene, the plan is shown, approved and run, and the camera confirms the way is clear. A recorded run exists | `docs/autonomy-demo.md`, `simulation/frames/autonomy_demo.mp4` (git-ignored; regenerate with `simulation/record_demo.py`) | Met (sim) |
| **Constraints.** Simulation acceptable | Blender twin and software rover; the real board path is also written | `simulation/blender_rover.py`, `laptop/sim_server.py` | Met |
| **Judging focus.** Object perception | Four perception methods, scale learned from the 40 mm blocks, optional calibration | `laptop/scale.py`, `laptop/calibrate.py` | Strong |
| ...decision-making | Cheapest safe route; heavy and hot blocks skipped with a reason shown | `laptop/route.py` | Strong |
| ...autonomous interaction | The rover runs the whole approved plan by itself and keeps going if the link drops | `firmware/rover_core.h` | Strong in sim; **unproven on hardware** |
| ...functionality | 800+ automated tests across Python, TypeScript and C++ | `pytest`, `npm test`, `ctest` | Strong |
| ...adaptability | See Stage 3 above | | Strong |
| ...innovation | Human-approved plan, camera-verified result, honest report with a fixed set of allowed summaries | `laptop/report.py` | Strong |

## Gaps that remain

These are real. None is hidden elsewhere in the repository.

1. **The physical rover has not run the loop end to end.** The 8 of 10 two-block benchmark (`docs/trials.csv`) is deferred, not passed. Wheel directions, servo directions and IR polarity are assumptions listed in `docs/demo-assumptions.md`. The brief accepts simulation, but any claim of a working physical rover must wait for the benchmark.
2. **The person detector is not wired into the operator page.** It works on real photographs, but it does not recognise the Blender figure, and the operator still finds the survivor by the light or by a tap (`docs/survivor-detection.md`, "Not done yet").
3. **Two firmware variants describe different arms.** The protocol firmware (`main.cpp`, ESP32-S3) drives a 4-servo arm; the Manual tab's firmware (`rover_arm_ap.cpp`, classic ESP32) drives a 5-servo arm. Decide which is the final robot before any hardware claim.
4. **No authentication on the rover's own network ports.** See `docs/production-readiness.md`.

## Suggested demo order for judges

1. Open the operator page. Show what the camera sees and what the planner chose and why (blocks to move, blocks left, with reasons).
2. Press **Approve plan**. Nothing moved before this.
3. While it runs, move a block that is not in the plan. The rover stops, the run is written up as a safe stop, and a fresh plan appears.
4. Approve the fresh plan. Show the camera confirming the way is clear, and the report.
5. Say plainly which parts are simulated.
