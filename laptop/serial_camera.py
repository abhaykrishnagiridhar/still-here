"""The rover's camera over the USB cable instead of Wi-Fi.

The rover (firmware/usb_video.cpp) sends each JPEG picture as one frame:

    A5 5A 53 48      magic ("SH" after two marker bytes)
    length           4 bytes, little endian: size of the JPEG
    sequence         4 bytes, little endian: counts up with every picture
    crc32            4 bytes, little endian: CRC-32 of the JPEG (the same one zlib.crc32 makes)
    check            1 byte: every one of the 16 bytes before it, xor-ed together
    JPEG             `length` bytes

The rover also prints status text on the same cable. The reader skips anything that is not a
frame, and drops a frame whose CRC is wrong, so a printed line landing in the middle of a picture
costs one picture and nothing else.

Use it as a source: `python server.py usb:COM9`. It looks like a cv2.VideoCapture to the rest of the program
(isOpened, read, release), so FrameSource can reconnect it like any other camera.
"""

import struct
import time
import zlib
from typing import Callable, Optional

import cv2
import numpy as np

MAGIC = b"\xa5\x5aSH"
HEADER_SIZE = 17
MAX_PAYLOAD = 300_000  # a JPEG of this camera is 10 to 60 KB; anything bigger is a damaged header
DEFAULT_BAUD = 2_000_000  # ignored by the board's native USB port, used by its UART port
READ_CHUNK = 4096
DEFAULT_WAIT_S = 1.0


def _xor(data: bytes) -> int:
    out = 0
    for byte in data:
        out ^= byte
    return out


def encode_frame(payload: bytes, seq: int) -> bytes:
    """One picture as the rover sends it. The firmware does the same; this is for tests and tools."""
    header = MAGIC + struct.pack("<III", len(payload), seq & 0xFFFFFFFF, zlib.crc32(payload))
    return header + bytes([_xor(header)]) + payload


class FrameParser:
    """Turns a stream of bytes into the JPEGs inside it. Feed it whatever arrives, in any pieces."""

    def __init__(self, max_payload: int = MAX_PAYLOAD) -> None:
        self._buffer = bytearray()
        self._max_payload = max_payload

    def feed(self, data: bytes) -> list[bytes]:
        self._buffer += data
        frames: list[bytes] = []
        while True:
            start = self._buffer.find(MAGIC)
            if start < 0:
                # Keep a tail that could be the start of the magic, drop the rest (text).
                del self._buffer[: max(0, len(self._buffer) - (len(MAGIC) - 1))]
                return frames
            del self._buffer[:start]
            if len(self._buffer) < HEADER_SIZE:
                return frames
            header = bytes(self._buffer[:16])
            length, _seq, crc = struct.unpack("<III", header[4:16])
            if self._buffer[16] != _xor(header) or length > self._max_payload:
                del self._buffer[:1]  # not a real header: look for the next magic
                continue
            end = HEADER_SIZE + length
            if len(self._buffer) < end:
                return frames  # wait for the rest of the picture
            payload = bytes(self._buffer[HEADER_SIZE:end])
            if zlib.crc32(payload) == crc:
                frames.append(payload)
                del self._buffer[:end]
            else:
                del self._buffer[:1]  # damaged: resume the search just after this magic


class SerialCamera:
    """What cv2.VideoCapture offers, over a serial port that sends the frames above."""

    def __init__(self, port, wait_s: float = DEFAULT_WAIT_S, clock: Callable[[], float] = time.monotonic) -> None:
        self._port = port
        self._wait_s = wait_s
        self._clock = clock
        self._parser = FrameParser()

    def isOpened(self) -> bool:
        return self._port is not None and bool(getattr(self._port, "is_open", True))

    def read(self) -> tuple[bool, Optional[np.ndarray]]:
        """The newest picture that arrives within the wait, or (False, None)."""
        if not self.isOpened():
            return False, None
        deadline = self._clock() + self._wait_s
        newest: Optional[bytes] = None
        while True:
            try:
                data = self._port.read(max(1, min(READ_CHUNK, getattr(self._port, "in_waiting", 0) or 1)))
            except (OSError, ValueError):
                self.release()  # the cable was pulled
                return False, None
            if data:
                frames = self._parser.feed(data)
                if frames:
                    newest = frames[-1]
                if newest is not None and not getattr(self._port, "in_waiting", 0):
                    break
            elif newest is not None or self._clock() >= deadline:
                break
            elif not getattr(self._port, "in_waiting", 0):
                time.sleep(0.002)
        if newest is None:
            return False, None
        image = cv2.imdecode(np.frombuffer(newest, dtype=np.uint8), cv2.IMREAD_COLOR)
        return (True, image) if image is not None else (False, None)

    def release(self) -> None:
        port, self._port = self._port, None
        if port is not None:
            try:
                port.close()
            except OSError:
                pass

    def set(self, *_args) -> bool:
        return False  # a webcam setting such as the buffer size: nothing to change here


def _open_pyserial(name: str, baud: int):
    import serial  # pyserial; imported late so the rest of the program does not need it

    return serial.Serial(name, baud, timeout=0.05)


def open_serial_camera(
    name: str,
    baud: int = DEFAULT_BAUD,
    *,
    opener: Callable = _open_pyserial,
    wait_s: float = DEFAULT_WAIT_S,
) -> SerialCamera:
    """A camera on the named port. If the port cannot be opened the camera reports it is closed,
    which FrameSource turns into a reconnect and, in the end, a message to the person."""
    try:
        port = opener(name, baud)
    except (OSError, ValueError, ImportError):
        return SerialCamera(None, wait_s=wait_s)
    return SerialCamera(port, wait_s=wait_s)
