"""A small console for driving the rover by hand, using the messages in docs/protocol.md.

    python firmware/rover_control.py                   the rover named in config.toml (still-here.local)
    python firmware/rover_control.py --rover 192.168.0.50 --speed 0.3

It is the same link the operator server uses (laptop/rover_link.py): it pings the rover every
0.5 s, so the rover knows you are there, and it never sends a command while the rover is
unreachable. Each drive button moves the wheels for half a second and then stops them. Lift the
wheels off the table for the first try.
"""

import argparse
import sys
import time
from pathlib import Path
from typing import Callable, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "laptop"))

from aruco import load_config  # noqa: E402
from plan_message import build_arm_pose_message, build_drive_message  # noqa: E402
from rover_link import RealLink  # noqa: E402

SEND_EVERY_S = 0.1  # a held command is repeated this often
DRIVE_FOR_S = 0.5  # how long one drive button keeps the wheels going
ARM_SPEED = 0.6
HOME_POSE = {"base": 0.0, "shoulder": 60.0, "elbow": -90.0, "gripper": 90.0}
CONNECT_WAIT_S = 5.0
DIRECTIONS = {"1": "forward", "2": "reverse", "3": "left", "4": "right"}

MENU = """
  1 Forward   2 Reverse   3 Left   4 Right     (half a second each)
  5 Stop
  6 Arm to home   7 Gripper open   8 Gripper closed   9 Arm pose (type the numbers)
  s Status        0 Exit (stops the wheels)
"""


def wheels_for(direction: str, speed: float) -> tuple[float, float]:
    """(left, right) wheel speeds. Turning spins on the spot: a faster right wheel turns left."""
    s = max(0.0, min(1.0, speed))
    return {
        "forward": (s, s),
        "reverse": (-s, -s),
        "left": (-s, s),
        "right": (s, -s),
    }[direction]


class Console:
    def __init__(
        self,
        link,
        *,
        speed: float = 0.3,
        say: Callable[[str], None] = print,
        ask: Callable[[str], str] = input,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._link, self._speed, self._say, self._ask, self._sleep = link, speed, say, ask, sleep
        self._pose = dict(HOME_POSE)
        self.state: Optional[dict] = None
        self.sensors: Optional[dict] = None

    # ---- sending ------------------------------------------------------------------
    def _send(self, message: dict) -> bool:
        if not self._link.send(message):
            self._say("The rover is not connected, so nothing was sent.")
            return False
        return True

    def _listen(self) -> None:
        """Take in what the rover has said since last time, and show anything notable."""
        for message in self._link.advance(0.0):
            if message["type"] == "state":
                self.state = message
            elif message["type"] == "sensors":
                self.sensors = message
            elif message["type"] == "event":
                self._say(f"  rover event: {message.get('code')} {message.get('detail', '')}".rstrip())
            elif message["type"] == "step_done" and not message.get("ok"):
                self._say(f"  step {message.get('step_id')} failed: {message.get('reason')}")

    def drive(self, direction: str, seconds: float = DRIVE_FOR_S) -> None:
        left, right = wheels_for(direction, self._speed)
        for _ in range(max(1, round(seconds / SEND_EVERY_S))):
            if not self._send(build_drive_message(left, right)):
                return
            self._sleep(SEND_EVERY_S)
        self._send(build_drive_message(0.0, 0.0))

    def stop(self) -> None:
        self._send(build_drive_message(0.0, 0.0))

    def move_arm(self, **changes: float) -> None:
        pose = {**self._pose, **changes}
        try:
            message = build_arm_pose_message(pose["base"], pose["shoulder"], pose["elbow"], pose["gripper"], ARM_SPEED)
        except ValueError as error:
            self._say(str(error))
            return
        if self._send(message):
            self._pose = {joint: message[joint] for joint in HOME_POSE}

    def ask_for_pose(self) -> None:
        try:
            numbers = [float(part) for part in self._ask("base shoulder elbow gripper (degrees, spaces between): ").split()]
        except ValueError:
            self._say("Those were not numbers.")
            return
        if len(numbers) != 4:
            self._say("Give exactly four numbers.")
            return
        self.move_arm(**dict(zip(HOME_POSE, numbers, strict=True)))

    def status(self) -> None:
        self._listen()
        if self.state is None:
            self._say("No state from the rover yet.")
            return
        self._say(f"  state: {self.state}")
        if self.sensors is not None:
            self._say(f"  sensors: {self.sensors}")

    # ---- the menu -----------------------------------------------------------------
    def handle(self, choice: str) -> bool:
        """Do one menu choice. Returns False when it is time to leave."""
        choice = choice.strip().lower()
        self._listen()
        if choice in DIRECTIONS:
            self.drive(DIRECTIONS[choice])
        elif choice == "5":
            self.stop()
        elif choice == "6":
            self.move_arm(**HOME_POSE)
        elif choice == "7":
            self.move_arm(gripper=90.0)
        elif choice == "8":
            self.move_arm(gripper=0.0)
        elif choice == "9":
            self.ask_for_pose()
        elif choice == "s":
            self.status()
        elif choice == "0":
            self.stop()
            return False
        elif choice:
            self._say("Unknown choice.")
        return True


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Drive the rover by hand from the console")
    parser.add_argument("--rover", help="the rover's name or address, optionally with a port (default: config.toml)")
    parser.add_argument("--speed", type=float, default=0.3, help="wheel speed from 0.1 to 1 (default 0.3)")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    if not 0.1 <= args.speed <= 1.0:
        print("--speed must be from 0.1 to 1", file=sys.stderr)
        return 1
    config = load_config()
    host, port = config.rover_host, config.ws_port
    if args.rover:
        host, _, port_text = args.rover.partition(":")
        if port_text:
            if not port_text.isdigit():
                print("--rover port must be a number", file=sys.stderr)
                return 1
            port = int(port_text)
    link = RealLink(host, port).start()
    try:
        print(f"Connecting to {link.address} ...")
        deadline = time.monotonic() + CONNECT_WAIT_S
        while not link.connected and time.monotonic() < deadline:
            time.sleep(0.1)
        if not link.connected:
            print(f"Could not reach the rover at {link.address}. {link.last_error}", file=sys.stderr)
            return 1
        console = Console(link, speed=args.speed)
        print(MENU)
        while console.handle(input("Choose: ")):
            pass
    except (KeyboardInterrupt, EOFError):
        print()
    finally:
        if link.connected:
            link.send(build_drive_message(0.0, 0.0))  # never leave the wheels running
            time.sleep(0.15)
        link.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
