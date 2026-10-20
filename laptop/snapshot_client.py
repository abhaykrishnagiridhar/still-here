"""The laptop's side of the snapshot request: ask the Blender twin for a picture and wait for it.

The message itself is built in snapshot_protocol.py, which Blender also imports. This part needs OpenCV to read the
picture, and Blender's own Python does not have it, so it lives here.
"""

import json
import socket
import time
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from snapshot_protocol import snapshot_packet


def request_picture(
    path, camera: str, host: str, port: int, wait_s: float = 8.0, poll_s: float = 0.005
) -> Optional[tuple[np.ndarray, dict]]:
    """Ask the twin for a picture and wait for it. Returns the picture and the sidecar (the small .json
    file written beside it), or None if nothing arrived in time. Any picture left from an earlier request
    is deleted first, so an old one is never taken for the new one."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    sidecar = path.with_suffix(".json")
    for old in (path, sidecar):
        try:
            old.unlink(missing_ok=True)
        except OSError:
            pass  # another program is reading it: the new picture overwrites it anyway
    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sender.sendto(snapshot_packet(path, camera), (host, port))
    finally:
        sender.close()
    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline:
        try:
            data = json.loads(sidecar.read_text(encoding="utf-8"))  # written last: when it parses, the picture is done
        except (OSError, ValueError):
            data = None
        if isinstance(data, dict):
            image = cv2.imread(str(path))
            if image is not None:
                return image, data
        time.sleep(poll_s)
    return None
