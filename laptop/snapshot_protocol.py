"""The message that asks the Blender twin for a picture of what its camera sees.

Blender listens on UDP for the rover commands that phone_bridge.py forwards. A snapshot request is a
second kind of packet on the same port:

    {"kind": "snapshot", "path": "<frames folder>/rover_view.png", "camera": "rover"}

Blender renders the named camera and writes the PNG at that path, so a separate program (the person
detector in survivor_check.py) can look at it. This module holds the parts that need no Blender, so they
can be tested: building the packet, and checking a received one. The check matters because anything on this
computer can send a datagram to the port: Blender only writes a .png inside the frames folder.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

CAMERAS = ("rover", "overview", "topdown")  # the rover front camera, a fixed view of the table, and a camera straight above it
DEFAULT_CAMERA = "rover"


@dataclass(frozen=True)
class Snapshot:
    path: Path
    camera: str


def snapshot_packet(path, camera: str = DEFAULT_CAMERA) -> bytes:
    """The datagram that asks Blender to write a picture from `camera` to `path`."""
    return json.dumps({"kind": "snapshot", "path": str(Path(path).resolve()), "camera": camera}).encode("utf-8")


def parse_snapshot(packet: Any, frames_dir) -> Optional[Snapshot]:
    """A request Blender may carry out, or None for anything else: another kind of packet, a bad shape,
    an unknown camera, a file that is not a .png, or a path that leaves the frames folder."""
    if not isinstance(packet, dict) or packet.get("kind") != "snapshot":
        return None
    raw_path = packet.get("path")
    camera = packet.get("camera", DEFAULT_CAMERA)
    if not isinstance(raw_path, str) or not raw_path.strip() or camera not in CAMERAS:
        return None
    path = Path(raw_path).resolve()
    root = Path(frames_dir).resolve()
    if path.suffix.lower() != ".png" or root not in path.parents:
        return None
    return Snapshot(path=path, camera=camera)

