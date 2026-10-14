"""Receives phone orientation and forwards rover-protocol commands to Blender over localhost UDP.

Run from the repo root (``still-here``) with the laptop virtual environment:
    laptop/.venv/Scripts/python -m uvicorn simulation.phone_bridge:app --host 0.0.0.0 --port 8765
Then open http://<laptop-ip>:8765/ on the phone. Plain http is used on purpose, so the page
is not a "secure context": on Chrome for Android set chrome://flags/#unsafely-treat-insecure-origin-as-secure
to that address, or the browser will not give the page tilt readings.
"""

from __future__ import annotations

import ipaddress
import json
import socket
import time
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

import sys

LAPTOP_DIR = Path(__file__).resolve().parents[1] / "laptop"
if str(LAPTOP_DIR) not in sys.path:
    sys.path.insert(0, str(LAPTOP_DIR))

from gyro_map import GyroSession

BLENDER_HOST = "127.0.0.1"
BLENDER_PORT = 8766
PHONE_PAGE = Path(__file__).resolve().parent / "phone_control.html"
WS_POLICY_VIOLATION = 1008


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


def origin_allowed(origin: str | None) -> bool:
    """Only pages served from this machine or the local network may drive the bridge.

    Browsers always send an Origin header, so a page on the public internet is refused. That
    stops it from opening this socket through the visitor's browser (cross-site hijacking).
    Clients that send no Origin, such as scripts, are not browsers and are allowed.
    """
    if not origin:
        return True
    host = urlparse(origin).hostname
    if host is None:
        return False
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_loopback or address.is_private or address.is_link_local


app = FastAPI(title="STILL HERE phone-to-Blender bridge")


@app.get("/")
def phone_page() -> FileResponse:
    """The tilt controller. Open http://<laptop-ip>:8765/ on the phone, on the same Wi-Fi."""
    return FileResponse(PHONE_PAGE)


@app.get("/health")
def health() -> dict:
    return {"ok": True, "blender_udp": f"{BLENDER_HOST}:{BLENDER_PORT}"}


@app.websocket("/phone")
async def phone_socket(websocket: WebSocket) -> None:
    if not origin_allowed(websocket.headers.get("origin")):
        await websocket.close(code=WS_POLICY_VIOLATION)
        return
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
