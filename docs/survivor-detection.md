# Finding the survivor with a pretrained person detector

A pretrained YOLOX-S network finds people in a picture. It was not trained on this project: it ships with the OpenCV model zoo, and OpenCV runs it, so there is no PyTorch and no training step.

## Files

| File | Role |
|---|---|
| `laptop/person_detector.py` | Picture in, boxes around people out. Works on any BGR picture. |
| `laptop/models/object_detection_yolox_2022nov_int8.onnx` | The model, 9,079,452 bytes. Not in git (see below). |
| `simulation/blender_rover.py` | The Blender twin now has a survivor figure, a camera on the rover, and a snapshot service. |
| `simulation/snapshot_protocol.py` | The UDP request that asks Blender for a picture, and the check that keeps Blender from writing outside `simulation/frames/`. |
| `simulation/survivor_check.py` | Asks Blender for a picture, runs the detector, reports where the survivor is. |

## Run it

1. Start Blender with the twin: `blender --python simulation/blender_rover.py`. A Blender started before this change must be restarted.
2. From `still-here`:

```powershell
laptop\.venv\Scripts\python.exe simulation\survivor_check.py
```

It prints one line of JSON: `source`, `survivor_px` (the point where the survivor stands, in picture pixels), `model_found`, and `model_agrees`. The marked-up picture is `simulation/frames/survivor_check.png`.

To look at a picture file (a real photo, for instance): `survivor_check.py --image photo.jpg`.

## What the model can and cannot do

- On real pictures it works. It found the person in a laptop-webcam screenshot (score 0.81) and a person in the background of a bench photo (0.78), and nothing in photos of hands and circuit boards.
- It does **not** see the twin's cartoon figure as a person. The raw person score on the Blender render is about zero, even enlarged. A network trained on photographs does not read a figure made of boxes and spheres as a person.
- So in the twin, Blender supplies the survivor's exact box (`view.json` beside each picture), and `survivor_check.py` reports whether the model agreed. With a real camera and a real person or doll, the model's box is used instead.
- It takes about 0.3 s a picture on a laptop CPU. Run it a few times a second, not on every frame.
- OpenCV 5's default DNN engine returns all zeros for this quantised model. `person_detector.py` asks for the classic engine, and a test guards that.

## The model file

The model is not committed. To get it again:

- Source: https://github.com/opencv/opencv_zoo, `models/object_detection_yolox/object_detection_yolox_2022nov_int8.onnx` (Git LFS, Apache-2.0)
- Download link that serves the real file: https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/object_detection_yolox/object_detection_yolox_2022nov_int8.onnx
- SHA-256 of the file used: `01a3b0f400b30bc1e45230e991b2e499ab42622485a330021947333fbaf03935`
- Save it in `laptop/models/`.

## Not done yet

- The operator page does not use the detector. The survivor is still found by the pulsing light or by a tap. Feeding `survivor_px` to the operator needs the picture and the operator's camera to be the same one, since its tap coordinates are in the server's own frame.
- The detector has not been run on the real rover camera with a person or doll in view.
