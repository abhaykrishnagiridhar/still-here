"""The software rover as a WebSocket server, behaving the way the real firmware has to.

    python sim_server.py                        listens on ws://127.0.0.1:81
    python sim_server.py --port 8081 --speed 5  another port, five times faster than real time
    python sim_server.py --scenario scenario_pick_drop.json    start with that scenario's blocks

With this running, `python server.py --rover 127.0.0.1` exercises the whole real-rover path (the
pages, the server, the WebSocket link and the protocol) before the real firmware exists, and
the same checks can be run against the real rover later.

Like the real rover must, it refuses pages from other websites: a browser sends an Origin header,
and only this machine or the local network may connect (origin_guard.py). It serves one
operator at a time.
"""

import argparse
import json
import sys
import threading
import time
from http import HTTPStatus
from pathlib import Path
from typing import Optional, Sequence

from websockets.exceptions import ConnectionClosed
from websockets.sync.server import serve

from models import Block
from origin_guard import origin_allowed
from scenario_runner import DEFAULT_SCENARIO, load_scenario, world_blocks
from sim_rover import SimRover

STEP_S = 0.05  # how often the rover's clock moves on
BUSY_CODE = 1013  # "try again later": someone else is already driving


class SimRoverServer:
    def __init__(
        self,
        blocks: Sequence[Block] = (),
        *,
        host: str = "127.0.0.1",
        port: int = 0,
        speed: float = 1.0,
    ) -> None:
        self.rover = SimRover(blocks)
        self._speed = speed
        self._lock = threading.Lock()
        self._busy = threading.Lock()  # held by the one connection that is driving
        self._server = serve(self._handle, host, port, process_request=self._check_origin)
        self.port: int = self._server.socket.getsockname()[1]
        self._thread: Optional[threading.Thread] = None

    def start(self) -> "SimRoverServer":
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def close(self) -> None:
        self._server.shutdown()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def _check_origin(self, connection, request):
        if not origin_allowed(request.headers.get("Origin")):
            return connection.respond(HTTPStatus.FORBIDDEN, "This page may not control the rover.\n")
        return None

    def _handle(self, connection) -> None:
        if not self._busy.acquire(blocking=False):
            connection.close(code=BUSY_CODE, reason="another operator is connected")
            return
        try:
            last = time.monotonic()
            while True:
                reply: list[dict] = []
                try:
                    raw = connection.recv(timeout=STEP_S)
                except TimeoutError:
                    raw = None
                except ConnectionClosed:
                    return
                if raw is not None:
                    try:
                        message = json.loads(raw)
                    except (TypeError, ValueError):
                        message = None
                    if isinstance(message, dict):  # anything else is not a protocol message
                        with self._lock:
                            reply += self.rover.handle(message)
                now = time.monotonic()
                if now - last >= STEP_S:
                    with self._lock:
                        reply += self.rover.step((now - last) * self._speed)
                    last = now
                for item in reply:
                    connection.send(json.dumps(item))
        except ConnectionClosed:
            return
        finally:
            self._busy.release()


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="The software rover as a WebSocket server")
    parser.add_argument("--host", default="127.0.0.1", help="use 0.0.0.0 to open it to the local network")
    parser.add_argument("--port", type=int, default=81)
    parser.add_argument("--speed", type=float, default=1.0, help="1 is real time, 5 is five times faster")
    parser.add_argument("--scenario", default=str(DEFAULT_SCENARIO), help="a scenario file whose blocks to start with")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    if args.speed <= 0:
        print("--speed must be greater than zero", file=sys.stderr)
        return 1
    try:
        blocks = world_blocks(load_scenario(Path(args.scenario)))
        server = SimRoverServer(blocks, host=args.host, port=args.port, speed=args.speed)
    except (OSError, ValueError) as error:
        print(f"Could not start: {error}", file=sys.stderr)
        return 1
    print(f"Software rover listening on ws://{args.host}:{server.port}  ({len(blocks)} blocks, speed {args.speed:g}). Ctrl-C stops it.")
    try:
        server.start()._thread.join()
    except KeyboardInterrupt:
        pass
    finally:
        server.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
