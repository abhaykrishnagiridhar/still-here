"""Manual control from the control page: drive the wheels and move the arm by hand.

The page keeps sending drive commands while a button is held. If they stop arriving (the button
was let go, the page closed, the Wi-Fi dropped), `tick()` stops the wheels itself, so the rover
never keeps driving on an old command. While an approved plan is running, manual commands are
refused so the two cannot fight over the rover.
"""

import time
from typing import Callable

from operator_core import Link, Outcome
from plan_message import build_abort_message, build_arm_pose_message, build_drive_message

WATCHDOG_S = 0.4  # no drive command for this long means stop the wheels


class Manual:
    def __init__(
        self,
        link: Link,
        *,
        is_busy: Callable[[], bool],
        clock: Callable[[], float] = time.monotonic,
        watchdog_s: float = WATCHDOG_S,
    ) -> None:
        self._link = link
        self._is_busy = is_busy
        self._clock = clock
        self._watchdog_s = watchdog_s
        self._driving = False
        self._last_drive = 0.0

    def _refuse_if_busy(self) -> Outcome | None:
        if self._is_busy():
            return Outcome(False, "A plan is running. Stop it first, then drive by hand.")
        return None

    def drive(self, left: float, right: float) -> Outcome:
        busy = self._refuse_if_busy()
        if busy is not None:
            return busy
        try:
            message = build_drive_message(left, right)
        except ValueError as error:
            return Outcome(False, str(error))
        self._link.send(message)
        self._driving = message["left"] != 0.0 or message["right"] != 0.0
        self._last_drive = self._clock()
        return Outcome(True, "Driving.")

    def arm_pose(self, base: float, shoulder: float, elbow: float, gripper: float, speed: float = 1.0) -> Outcome:
        busy = self._refuse_if_busy()
        if busy is not None:
            return busy
        try:
            message = build_arm_pose_message(base, shoulder, elbow, gripper, speed)
        except ValueError as error:
            return Outcome(False, str(error))
        self._link.send(message)
        return Outcome(True, "Arm moving.")

    def stop(self) -> Outcome:
        """Stop the wheels. If a plan is running this asks the rover to abort it."""
        self._link.send(build_drive_message(0.0, 0.0))
        self._driving = False
        if self._is_busy():
            self._link.send(build_abort_message())
        return Outcome(True, "Stopped.")

    def tick(self) -> None:
        """Call regularly. Stops the wheels, once, if the drive commands stopped coming."""
        if self._driving and self._clock() - self._last_drive > self._watchdog_s:
            self._link.send(build_drive_message(0.0, 0.0))
            self._driving = False
