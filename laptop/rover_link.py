"""The server's link to the real rover: a WebSocket that keeps itself connected.

    link = RealLink("still-here.local")      # the rover's name on the network, or an address
    link.start()
    link.send({"type": "plan", ...})         # False if the rover is not connected right now
    messages = link.advance(0.05)            # what the rover has sent since the last call

It follows docs/protocol.md: a `ping` goes out every 0.5 s, so the rover knows the link is alive
(after 2 s of silence it stops the wheels, or carries on with a stored plan). If the connection
drops, it keeps trying to reconnect by itself. Commands are never queued while the rover is
unreachable: a drive command delivered seconds late is dangerous, so it is refused instead and
the caller is told.
"""

import json
import logging
import threading
import time
from collections import deque
from typing import Callable, Optional

from websockets.exceptions import WebSocketException
from websockets.sync.client import connect

from plan_message import encode_message

log = logging.getLogger("still_here.rover_link")

PING_S = 0.5  # docs/protocol.md
RETRY_S = 1.0  # wait before trying to reconnect
OPEN_TIMEOUT_S = 2.0
TICK_S = 0.05  # how often the link thread looks for something to send


class RealLink:
    def __init__(
        self,
        host: str,
        port: int = 81,
        *,
        ping_s: float = PING_S,
        retry_s: float = RETRY_S,
        open_timeout_s: float = OPEN_TIMEOUT_S,
        opener: Optional[Callable] = None,
    ) -> None:
        self.host, self.port = host, port
        self._url = f"ws://{host}:{port}"
        self._ping_s, self._retry_s, self._open_timeout_s = ping_s, retry_s, open_timeout_s
        self._open = opener or connect
        self._inbox: deque[dict] = deque()
        self._outbox: deque[str] = deque()
        self._connected = threading.Event()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_error = ""

    # ---- what the server asks ----------------------------------------------------
    @property
    def address(self) -> str:
        return self._url

    @property
    def connected(self) -> bool:
        return self._connected.is_set()

    @property
    def last_error(self) -> str:
        """Why the last connection attempt failed, or an empty string."""
        return self._last_error

    def start(self) -> "RealLink":
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, daemon=True, name="rover-link")
            self._thread.start()
        return self

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3)
            self._thread = None

    def send(self, message: dict) -> bool:
        """Send one protocol message. Returns False, and sends nothing, if the rover is not
        connected. Raises ValueError for something that is not a protocol message."""
        text = encode_message(message)
        if not self.connected:
            return False
        self._outbox.append(text)
        return True

    def advance(self, dt: float) -> list[dict]:
        """The messages the rover has sent since the last call. (dt is unused: the real rover
        keeps its own time.)"""
        out = []
        while self._inbox:
            out.append(self._inbox.popleft())
        return out

    # ---- the connection thread ---------------------------------------------------
    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                with self._open(self._url, open_timeout=self._open_timeout_s) as ws:
                    self._outbox.clear()  # nothing from before this connection
                    self._connected.set()
                    self._last_error = ""
                    self._serve(ws)
            except (OSError, TimeoutError, WebSocketException) as error:
                self._last_error = f"{type(error).__name__}: {error}"
            except Exception as error:  # anything else must not end the thread: keep trying to reconnect
                self._last_error = f"{type(error).__name__}: {error}"
                log.exception("rover link failed unexpectedly; reconnecting")
            finally:
                self._connected.clear()
                self._outbox.clear()
            self._stop.wait(self._retry_s)

    def _serve(self, ws) -> None:
        next_ping = 0.0
        while not self._stop.is_set():
            now = time.monotonic()
            if now >= next_ping:
                ws.send(encode_message({"type": "ping", "t": round(now, 3)}))
                next_ping = now + self._ping_s
            while self._outbox:
                ws.send(self._outbox.popleft())
            try:
                raw = ws.recv(timeout=TICK_S)
            except TimeoutError:
                continue
            try:
                message = json.loads(raw)
            except (TypeError, ValueError):
                continue
            if isinstance(message, dict) and isinstance(message.get("type"), str):
                self._inbox.append(message)
