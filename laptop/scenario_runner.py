"""Replay a scenario of rover messages against the software rover, or against a real rover.

A scenario is a JSON file: a list of steps, each either something to SEND to the rover or
something to WAIT FOR from it (every field you list must match the rover's message). The
messages are the ones in docs/protocol.md, so the same file tests the software rover now and
the real firmware later.

    python scenario_runner.py                          the bundled pick and drop, software rover
    python scenario_runner.py my_scenario.json         another scenario
    python scenario_runner.py --target real --ip 192.168.0.50 --confirm-real

A real run can move the rover and its arm. Lift the wheels off the table and keep the arm area
clear first, which is why --confirm-real is required. The runner pings every 0.5 s like the
laptop does, so the rover does not think the link was lost.
"""

import argparse
import json
import sys
import time
from contextlib import ExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Protocol, Sequence

from models import Block
from plan_message import encode_message
from sim_rover import SimRover

LAPTOP_DIR = Path(__file__).resolve().parent
DEFAULT_SCENARIO = LAPTOP_DIR / "scenario_pick_drop.json"
POLL_S = 0.05
PING_S = 0.5
DEFAULT_TIMEOUT_S = 5.0


class Target(Protocol):
    def send(self, message: dict) -> None: ...
    def poll(self, seconds: float) -> list[dict]: ...
    def close(self) -> None: ...


@dataclass(frozen=True)
class StepResult:
    index: int
    label: str
    ok: bool
    detail: str


@dataclass
class Report:
    results: list[StepResult] = field(default_factory=list)
    messages: list[dict] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return bool(self.results) and all(r.ok for r in self.results)


# --- reading a scenario ---------------------------------------------------------------


def _check_step(index: int, step: Any) -> None:
    where = f"step {index}"
    if not isinstance(step, dict):
        raise ValueError(f"{where} must be an object")
    if "send" in step and "wait_for" in step:
        raise ValueError(f"{where} has only one of send or wait_for, not both")
    if "send" in step:
        if not isinstance(step["send"], dict) or not isinstance(step["send"].get("type"), str):
            raise ValueError(f"{where}: send needs an object with a text 'type'")
    elif "wait_for" in step:
        if not isinstance(step["wait_for"], dict) or not step["wait_for"]:
            raise ValueError(f"{where}: wait_for must be a non-empty object")
        timeout = step.get("timeout_s", DEFAULT_TIMEOUT_S)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
            raise ValueError(f"{where}: timeout_s must be greater than zero")
    else:
        raise ValueError(f"{where} needs send or wait_for")


def load_scenario(path: Path) -> dict:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"scenario file {path} not found")
    try:
        scenario = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"{path.name} is not valid JSON: {error}") from error
    if not isinstance(scenario, dict):
        raise ValueError(f"{path.name}: the scenario must be an object")
    steps = scenario.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ValueError(f"{path.name}: steps must be a non-empty list")
    for index, step in enumerate(steps, start=1):
        _check_step(index, step)
    return scenario


# --- the two kinds of rover -----------------------------------------------------------


class SimTarget:
    """The software rover, set up with the blocks the scenario lists. Time moves only when
    poll() is called, so a scenario runs far faster than real time."""

    def __init__(self, scenario: dict) -> None:
        blocks = [
            Block(id=b["id"], marker_id=b["id"], x=float(b["x"]), y=float(b["y"]), layer=b.get("layer", 1))
            for b in scenario.get("world", {}).get("blocks", [])
        ]
        self.rover = SimRover(blocks)
        self._inbox: list[dict] = []
        self._since_ping = PING_S

    def send(self, message: dict) -> None:
        self._inbox += self.rover.handle(message)

    def poll(self, seconds: float) -> list[dict]:
        out = self._inbox
        self._inbox = []
        for _ in range(max(1, round(seconds / POLL_S))):
            self._since_ping += POLL_S
            if self._since_ping >= PING_S:
                self._since_ping = 0.0
                out += self.rover.handle({"type": "ping", "t": self.rover.t})
            out += self.rover.step(POLL_S)
        return out

    def close(self) -> None:
        pass


class RealTarget:
    """A real rover (or a stand-in) over its WebSocket, with a ping every 0.5 s."""

    def __init__(self, host: str, port: int, timeout: float = 5.0) -> None:
        from websockets.sync.client import connect

        self._url = f"ws://{host}:{port}"
        self._stack = ExitStack()  # keeps the connection open until close()
        try:
            self._connection = self._stack.enter_context(connect(self._url, open_timeout=timeout))
        except (OSError, TimeoutError) as error:
            raise ConnectionError(f"Could not connect to {self._url}: {error}") from error
        self._last_ping = 0.0

    def send(self, message: dict) -> None:
        self._connection.send(encode_message(message))

    def poll(self, seconds: float) -> list[dict]:
        from websockets.exceptions import ConnectionClosed

        out: list[dict] = []
        deadline = time.monotonic() + seconds
        try:
            if time.monotonic() - self._last_ping >= PING_S:
                self._last_ping = time.monotonic()
                self.send({"type": "ping", "t": self._last_ping})
            while (remaining := deadline - time.monotonic()) > 0:
                try:
                    out.append(json.loads(self._connection.recv(timeout=remaining)))
                except TimeoutError:
                    break
        except ConnectionClosed as error:
            raise ConnectionError(f"The rover closed the connection: {error}") from error
        return out

    def close(self) -> None:
        self._stack.close()


# --- running ---------------------------------------------------------------------------


def _matches(message: dict, wanted: dict) -> bool:
    return all(key in message and message[key] == value for key, value in wanted.items())


def run_scenario(scenario: dict, target: Target) -> Report:
    """Run the steps in order and stop at the first one that fails."""
    report = Report()
    cursor = 0  # messages before this were already used by an earlier wait
    for index, step in enumerate(scenario["steps"], start=1):
        if "send" in step:
            target.send(step["send"])
            report.results.append(StepResult(index, f"send {step['send']['type']}", True, "sent"))
            continue
        wanted, timeout = step["wait_for"], step.get("timeout_s", DEFAULT_TIMEOUT_S)
        label = f"wait for {json.dumps(wanted, sort_keys=True)}"
        waited = 0.0
        found: Optional[int] = None
        while True:
            found = next((i for i in range(cursor, len(report.messages)) if _matches(report.messages[i], wanted)), None)
            if found is not None or waited >= timeout:
                break
            report.messages += target.poll(POLL_S)
            waited += POLL_S
        if found is None:
            report.results.append(StepResult(index, label, False, f"no message matching {wanted} within {timeout:g} s"))
            break
        cursor = found + 1
        report.results.append(StepResult(index, label, True, f"got {report.messages[found]}"))
    return report


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Replay a scenario against the software or a real rover")
    parser.add_argument("scenario", nargs="?", default=str(DEFAULT_SCENARIO))
    parser.add_argument("--target", choices=["sim", "real"], default="sim")
    parser.add_argument("--ip", help="the rover's address (needed for --target real)")
    parser.add_argument("--port", type=int, default=81)
    parser.add_argument("--confirm-real", action="store_true", help="yes, this may move the real rover")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    if args.target == "real" and not args.ip:
        print("--ip is required with --target real", file=sys.stderr)
        return 2
    if args.target == "real" and not args.confirm_real:
        print("A real run can move the rover and its arm. Lift the wheels, clear the arm area, "
              "then add --confirm-real.", file=sys.stderr)
        return 2
    try:
        scenario = load_scenario(Path(args.scenario))
        target: Target = SimTarget(scenario) if args.target == "sim" else RealTarget(args.ip, args.port)
    except (OSError, ValueError, ConnectionError) as error:
        print(str(error), file=sys.stderr)
        return 1
    print(f"Scenario: {scenario.get('name', Path(args.scenario).name)} ({args.target})")
    try:
        report = run_scenario(scenario, target)
    except ConnectionError as error:
        print(str(error), file=sys.stderr)
        return 1
    finally:
        target.close()
    for result in report.results:
        print(f"{'PASS' if result.ok else 'FAIL'} step {result.index}: {result.label}"
              + ("" if result.ok else f"  ({result.detail})"))
    failed = sum(1 for r in report.results if not r.ok)
    if report.passed:
        print("\nRESULT: all steps passed")
    else:
        print(f"\nRESULT: {len(report.results) - failed} passed, {failed} failed")
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
