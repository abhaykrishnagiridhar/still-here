"""A frame source that reconnects by itself when a network camera drops out.

The rover camera's stream over Wi-Fi stalls now and then. This reads pictures, puts up with a few
failed reads in a row, then closes the stream and opens it again. After too many failed
reconnects in a row it gives up, so the program can say so instead of hanging.
"""

import time
from typing import Callable, Optional, Protocol

import numpy as np


class Capture(Protocol):
    def isOpened(self) -> bool: ...
    def read(self) -> tuple[bool, Optional[np.ndarray]]: ...
    def release(self) -> None: ...


class FrameSource:
    def __init__(
        self,
        open_capture: Callable[[], Capture],
        *,
        max_failed_reads: int = 30,
        max_reconnects: int = 5,
        retry_delay_s: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if max_failed_reads < 1:
            raise ValueError("max_failed_reads must be at least 1")
        if max_reconnects < 0:
            raise ValueError("max_reconnects must not be negative")
        if retry_delay_s < 0:
            raise ValueError("retry_delay_s must not be negative")
        self._open_capture = open_capture
        self._max_failed_reads = max_failed_reads
        self._max_reconnects = max_reconnects
        self._retry_delay_s = retry_delay_s
        self._sleep = sleep
        self._reconnects = 0
        self.gave_up = False

        self._capture = open_capture()
        self._failed_reads = 0 if self._capture.isOpened() else max_failed_reads + 1

    def read(self) -> Optional[np.ndarray]:
        """The next picture, or None if there is none right now (or the source has given up)."""
        if self.gave_up:
            return None

        ok, frame = self._capture.read()
        if ok and frame is not None and frame.size > 0:
            self._failed_reads = 0
            self._reconnects = 0
            return frame

        self._failed_reads += 1
        if self._failed_reads > self._max_failed_reads:
            self._reconnect()
        return None

    def close(self) -> None:
        self._capture.release()

    def _reconnect(self) -> None:
        self._capture.release()
        if self._reconnects >= self._max_reconnects:
            self.gave_up = True
            return
        self._reconnects += 1
        self._sleep(self._retry_delay_s)
        self._capture = self._open_capture()
        self._failed_reads = 0 if self._capture.isOpened() else self._max_failed_reads + 1
