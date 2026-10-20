"""The operator's link to the rover in the Blender twin, over UDP on this computer.

It stands in for rover_link.RealLink: the same few things (send, advance, connected, address, last_error), so the
operator and the pages cannot tell the difference. A command goes out as

    {"kind": "command", "reply": true, "message": {...}}

and the twin answers every packet that says "reply" by sending back everything its rover says (state, step_done,
events), each as {"kind": "rover", "message": {...}}. Like the real laptop it pings every half second, so the
rover's link-loss rule never fires while the server is running.
"""

import json
import socket
import time
from typing import Callable

PING_S = 0.5
TIMEOUT_S = 2.0  # silence from the twin for this long counts as not connected (it sends state five times a second)
RECEIVE_BYTES = 65535


class BlenderLink:
    supports_world_reset = True  # the twin understands `reset_world` and `overlay` (see autopilot.py)

    def __init__(
        self,
        port: int,
        host: str = "127.0.0.1",
        *,
        clock: Callable[[], float] = time.monotonic,
        ping_s: float = PING_S,
        timeout_s: float = TIMEOUT_S,
    ) -> None:
        self._target = (host, port)
        self._clock = clock
        self._ping_s = ping_s
        self._timeout_s = timeout_s
        self._since_ping = ping_s  # ping straight away, so the twin learns where to answer
        self._last_heard: float | None = None
        self.address = f"the Blender twin at {host}:{port}"
        self.last_error = ""
        self._socket: socket.socket | None = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.setblocking(False)

    @property
    def connected(self) -> bool:
        return self._last_heard is not None and self._clock() - self._last_heard <= self._timeout_s

    def send(self, message: dict) -> None:
        """Hand one rover command to the twin. If it cannot be sent, say why and carry on."""
        if self._socket is None:
            self.last_error = "the link to the Blender twin is closed"
            return
        packet = json.dumps({"kind": "command", "reply": True, "message": message}).encode("utf-8")
        try:
            self._socket.sendto(packet, self._target)
        except OSError as problem:
            self.last_error = str(problem)

    def advance(self, dt: float) -> list[dict]:
        """Ping when it is time, and return what the rover has said since the last call."""
        if self._socket is None:
            return []
        self._since_ping += dt
        if self._since_ping >= self._ping_s:
            self._since_ping = 0.0
            self.send({"type": "ping", "t": self._clock()})
        out: list[dict] = []
        while True:
            try:
                raw, _ = self._socket.recvfrom(RECEIVE_BYTES)
            except (BlockingIOError, ConnectionResetError):
                break  # nothing more waiting (Windows reports an unanswered send as a reset: not an error)
            except OSError as problem:
                self.last_error = str(problem)
                break
            message = self._parse(raw)
            if message is not None:
                self._last_heard = self._clock()
                self.last_error = ""
                out.append(message)
        return out

    @staticmethod
    def _parse(raw: bytes) -> dict | None:
        try:
            packet = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return None
        if not isinstance(packet, dict) or packet.get("kind") != "rover":
            return None
        message = packet.get("message")
        return message if isinstance(message, dict) else None

    def close(self) -> None:
        sock, self._socket = self._socket, None
        if sock is not None:
            sock.close()
