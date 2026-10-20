"""The camera over the USB cable: pictures arrive as framed JPEGs among stray text."""

import struct
import zlib

import cv2
import numpy as np
import pytest

from serial_camera import MAGIC, FrameParser, SerialCamera, encode_frame, open_serial_camera


def jpeg(value=128, size=(48, 64)):
    image = np.full((size[0], size[1], 3), value, dtype=np.uint8)
    ok, data = cv2.imencode(".jpg", image)
    assert ok
    return data.tobytes()


def xor_of(data):
    out = 0
    for byte in data:
        out ^= byte
    return out


class FakePort:
    """Stands in for a serial port: hands out the bytes it was given, a few at a time."""

    def __init__(self, data=b"", chunk=64):
        self.data = bytearray(data)
        self.chunk = chunk
        self.closed = False
        self.is_open = True

    @property
    def in_waiting(self):
        return len(self.data)

    def read(self, count):
        count = min(count, self.chunk, len(self.data))
        out = bytes(self.data[:count])
        del self.data[:count]
        return out

    def close(self):
        self.closed = True
        self.is_open = False


# ---- the frame format ---------------------------------------------------------------------


def test_a_frame_has_the_agreed_header():
    payload = jpeg()
    frame = encode_frame(payload, seq=7)

    assert frame[:4] == MAGIC == b"\xa5\x5aSH"
    length, seq, crc = struct.unpack("<III", frame[4:16])
    assert (length, seq, crc) == (len(payload), 7, zlib.crc32(payload))
    assert frame[16] == xor_of(frame[:16])
    assert frame[17:] == payload


def test_one_whole_frame_comes_out_once():
    parser = FrameParser()
    payload = jpeg()

    assert parser.feed(encode_frame(payload, 1)) == [payload]
    assert parser.feed(b"") == []


def test_a_frame_split_into_tiny_pieces_still_comes_out():
    parser = FrameParser()
    payload = jpeg()
    out = []
    for byte in encode_frame(payload, 1):
        out += parser.feed(bytes([byte]))
    assert out == [payload]


def test_text_between_frames_is_skipped():
    parser = FrameParser()
    a, b = jpeg(10), jpeg(200)
    data = b"camera: 8.7 fps\r\n" + encode_frame(a, 1) + b"link: up\r\n" + encode_frame(b, 2)

    assert parser.feed(data) == [a, b]


def test_a_frame_with_a_damaged_picture_is_dropped_and_the_next_one_survives():
    parser = FrameParser()
    good = jpeg(90)
    bad = bytearray(encode_frame(jpeg(10), 1))
    bad[-5] ^= 0xFF  # a stray byte, such as a printed line, lands inside the picture

    assert parser.feed(bytes(bad) + encode_frame(good, 2)) == [good]


def test_a_header_that_lies_about_its_length_is_ignored():
    parser = FrameParser(max_payload=1000)
    huge = MAGIC + struct.pack("<III", 5_000_000, 1, 0)
    huge += bytes([xor_of(huge)])

    assert parser.feed(huge + encode_frame(jpeg(), 2)) == [jpeg()]


def test_a_header_with_a_bad_check_byte_is_ignored():
    parser = FrameParser()
    frame = bytearray(encode_frame(jpeg(), 1))
    frame[16] ^= 0x55

    assert parser.feed(bytes(frame)) == []


# ---- the camera ---------------------------------------------------------------------------


def test_read_gives_the_newest_picture_as_an_image():
    port = FakePort(encode_frame(jpeg(10), 1) + encode_frame(jpeg(200), 2))
    camera = SerialCamera(port, wait_s=0.5)

    ok, image = camera.read()

    assert ok and image.shape == (48, 64, 3)
    assert image.mean() > 150  # the second, brighter picture, not the first


def test_read_waits_for_a_picture_then_gives_up_quietly():
    camera = SerialCamera(FakePort(b""), wait_s=0.05)

    ok, image = camera.read()

    assert ok is False and image is None


def test_release_closes_the_port():
    port = FakePort()
    camera = SerialCamera(port)

    camera.release()

    assert port.closed and camera.isOpened() is False


def test_a_closed_port_reads_nothing():
    port = FakePort(encode_frame(jpeg(), 1))
    camera = SerialCamera(port)
    camera.release()

    assert camera.read() == (False, None)


def test_a_port_that_will_not_open_gives_a_closed_camera():
    def refuse(name, baud):
        raise OSError("port busy")

    camera = open_serial_camera("COM7", opener=refuse)

    assert camera.isOpened() is False
    assert camera.read() == (False, None)


def test_a_port_that_opens_gives_a_working_camera():
    port = FakePort(encode_frame(jpeg(), 1))
    camera = open_serial_camera("COM7", opener=lambda name, baud: port, wait_s=0.5)

    ok, image = camera.read()

    assert ok and image is not None


def test_open_source_understands_usb_names():
    import vision

    seen = {}

    def fake(name, baud):
        seen["name"] = name
        return FakePort()

    camera = vision.open_source("usb:COM9", usb_opener=fake)

    assert seen["name"] == "COM9"
    assert isinstance(camera, SerialCamera)


@pytest.mark.parametrize("bad", ["usb:", "usb:   "])
def test_an_empty_usb_name_is_refused(bad):
    import vision

    with pytest.raises(ValueError):
        vision.open_source(bad)
