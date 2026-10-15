"""Receives phone orientation and forwards rover-protocol commands to Blender over localhost UDP.

Run from ``still-here`` after installing the existing project dependencies:
    python -m uvicorn simulation.phone_bridge:app --host 0.0.0.0 --port 8765
"""

from __future__ import annotations

import asyncio
import json
import socket
import time
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

import sys

LAPTOP_DIR = Path(__file__).resolve().parents[1] / "laptop"
if str(LAPTOP_DIR) not in sys.path:
    sys.path.insert(0, str(LAPTOP_DIR))

from gyro_map import GyroSession
from origin_guard import origin_allowed

BLENDER_HOST = "127.0.0.1"
BLENDER_PORT = 8766
WS_POLICY_VIOLATION = 1008  # A non-local web page may not control the rover.


class PhoneBridge:
    """Small, testable adapter between browser samples and Blender UDP packets."""

    def __init__(self) -> None:
        self.session = GyroSession()

    def handle_all(self, sample: dict, now: float) -> list[dict]:
        """Convert one browser sample into every command it entails.

        A mode change includes a safe drive stop before the first arm command;
        emitting the whole list preserves that safety contract over UDP.
        """
        commands = self.session.update(sample, now)
        return [{"kind": "command", "message": command} for command in commands]

    def handle(self, sample: dict, now: float) -> dict | None:
        """Compatibility helper for callers that expect only the final command."""
        packets = self.handle_all(sample, now)
        return packets[-1] if packets else None

    def idle(self, now: float) -> list[dict]:
        """Return the one safe-stop packet when phone samples go stale."""
        return [{"kind": "command", "message": command} for command in self.session.idle(now)]


app = FastAPI(title="STILL HERE phone-to-Blender bridge")

EMERGENCY_STOP_MESSAGES = (
    {"type": "abort"},
    {"type": "drive", "left": 0.0, "right": 0.0},
)


def send_emergency_stop() -> None:
    """Stop wheels and abort the active arm showcase without relying on WebSocket state."""
    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        for message in EMERGENCY_STOP_MESSAGES:
            packet = {"kind": "command", "message": message}
            udp.sendto(json.dumps(packet).encode("utf-8"), (BLENDER_HOST, BLENDER_PORT))
    finally:
        udp.close()


@app.get("/health")
def health() -> dict:
    return {"ok": True, "blender_udp": f"{BLENDER_HOST}:{BLENDER_PORT}"}


@app.get("/")
def phone_control() -> FileResponse:
    """Serve the mobile controller from the same origin as its WebSocket."""
    return FileResponse(Path(__file__).with_name("phone_control.html"))


@app.post("/stop")
def emergency_stop() -> dict:
    """Emergency path used by the red phone button, even with a dead WebSocket."""
    send_emergency_stop()
    return {"ok": True}


@app.websocket("/phone")
async def phone_socket(websocket: WebSocket) -> None:
    # Do not let a public web page use a visitor's browser to control the rover.
    if not origin_allowed(websocket.headers.get("origin")):
        await websocket.close(code=WS_POLICY_VIOLATION)
        return
    await websocket.accept()
    bridge = PhoneBridge()
    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        while True:
            try:
                incoming = await asyncio.wait_for(websocket.receive_text(), timeout=0.1)
            except TimeoutError:
                for packet in bridge.idle(time.monotonic()):
                    udp.sendto(json.dumps(packet).encode("utf-8"), (BLENDER_HOST, BLENDER_PORT))
                continue
            try:
                sample = json.loads(incoming)
                packets = bridge.handle_all(sample, time.monotonic())
            except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
                continue  # one unreadable sample is skipped; it never reaches the rover
            for packet in packets:
                udp.sendto(json.dumps(packet).encode("utf-8"), (BLENDER_HOST, BLENDER_PORT))
    except WebSocketDisconnect:
        pass  # the stop below covers this
    finally:
        # Whatever ended the connection (the phone left, bad data, or a crash in this handler), tell
        # Blender to stop. Failing open would leave the last drive command running.
        try:
            send_emergency_stop()
        finally:
            udp.close()
