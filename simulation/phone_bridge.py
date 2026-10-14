"""Receives phone orientation and forwards rover-protocol commands to Blender over localhost UDP.

Run from ``still-here/laptop`` after installing the existing project dependencies:
    uvicorn simulation.phone_bridge:app --host 0.0.0.0 --port 8765
"""

from __future__ import annotations

import json
import socket
import time
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

import sys

LAPTOP_DIR = Path(__file__).resolve().parents[1] / "laptop"
if str(LAPTOP_DIR) not in sys.path:
    sys.path.insert(0, str(LAPTOP_DIR))

from gyro_map import GyroSession

BLENDER_HOST = "127.0.0.1"
BLENDER_PORT = 8766


class PhoneBridge:
    """Small, testable adapter between browser samples and Blender UDP packets."""

    def __init__(self) -> None:
        self.session = GyroSession()

    def handle(self, sample: dict, now: float) -> dict | None:
        commands = self.session.update(sample, now)
        if not commands:
            return None
        # Mode changes intentionally emit a stop then the new command. Blender can apply both in order.
        return {"kind": "command", "message": commands[-1]}


app = FastAPI(title="STILL HERE phone-to-Blender bridge")


@app.get("/health")
def health() -> dict:
    return {"ok": True, "blender_udp": f"{BLENDER_HOST}:{BLENDER_PORT}"}


@app.websocket("/phone")
async def phone_socket(websocket: WebSocket) -> None:
    await websocket.accept()
    bridge = PhoneBridge()
    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        while True:
            incoming = await websocket.receive_text()
            try:
                sample = json.loads(incoming)
            except json.JSONDecodeError:
                continue
            packet = bridge.handle(sample, time.monotonic())
            if packet is not None:
                udp.sendto(json.dumps(packet).encode("utf-8"), (BLENDER_HOST, BLENDER_PORT))
    except WebSocketDisconnect:
        # Blender receives an explicit safe stop when the phone page goes away.
        stop = {"kind": "command", "message": {"type": "drive", "left": 0.0, "right": 0.0}}
        udp.sendto(json.dumps(stop).encode("utf-8"), (BLENDER_HOST, BLENDER_PORT))
    finally:
        udp.close()
