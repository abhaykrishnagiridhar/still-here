"""The Blender twin's top-down camera as a frame source, so the whole vision pipeline can run on its pictures.

It looks like cv2.VideoCapture to the rest of the program (isOpened, read, release): each read asks the running
twin for a fresh picture of the table from above (see snapshot_protocol.py) and waits for it. Use it as a source:
`python server.py blender:8766`. Blender must be running simulation/blender_rover.py.
"""

import os
from pathlib import Path
from typing import Optional

import numpy as np

from snapshot_client import request_picture

DEFAULT_FRAMES_DIR = Path(__file__).resolve().parent.parent / "simulation" / "frames"  # the only place Blender writes
DEFAULT_WAIT_S = 3.0


class BlenderCamera:
    def __init__(
        self,
        port: int,
        host: str = "127.0.0.1",
        camera: str = "topdown",
        frames_dir=None,
        wait_s: float = DEFAULT_WAIT_S,
    ) -> None:
        self._port = port
        self._host = host
        self._camera = camera
        self._path = Path(frames_dir if frames_dir is not None else DEFAULT_FRAMES_DIR) / f"{camera}_view_{os.getpid()}.png"
        self._wait_s = wait_s
        self._open = True

    def isOpened(self) -> bool:
        return self._open

    def read(self) -> tuple[bool, Optional[np.ndarray]]:
        """A fresh picture, or (False, None) if Blender did not answer in time."""
        if not self._open:
            return False, None
        result = request_picture(self._path, self._camera, self._host, self._port, self._wait_s)
        if result is None:
            return False, None
        return True, result[0]

    def release(self) -> None:
        self._open = False

    def set(self, *_args) -> bool:
        return False  # a webcam setting such as the buffer size: nothing to change here
