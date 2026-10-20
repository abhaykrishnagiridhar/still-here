"""The Blender twin as a camera: each read asks for a fresh picture of the table from above."""

import json
import socket
import threading

import cv2
import numpy as np
import pytest

import vision
from blender_camera import BlenderCamera
from snapshot_protocol import parse_snapshot


class Answerer(threading.Thread):
    """Plays Blender: answers every snapshot request with a flat grey picture."""

    def __init__(self, frames_dir):
        super().__init__(daemon=True)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.settimeout(0.1)
        self.port = self.sock.getsockname()[1]
        self.frames_dir = frames_dir
        self.cameras = []
        self.stop = False

    def run(self):
        while not self.stop:
            try:
                raw, _ = self.sock.recvfrom(4096)
            except OSError:
                continue
            request = parse_snapshot(json.loads(raw), self.frames_dir)
            if request is not None:
                self.cameras.append(request.camera)
                cv2.imwrite(str(request.path), np.full((48, 64, 3), 99, dtype=np.uint8))
                request.path.with_suffix(".json").write_text("{}", encoding="utf-8")


@pytest.fixture
def blender(tmp_path):
    answerer = Answerer(tmp_path)
    answerer.start()
    yield answerer
    answerer.stop = True
    answerer.sock.close()


def test_read_gives_a_picture_from_the_top_down_camera(blender, tmp_path):
    camera = BlenderCamera(blender.port, frames_dir=tmp_path, wait_s=3.0)

    ok, image = camera.read()

    assert ok and image.shape == (48, 64, 3)
    assert blender.cameras == ["topdown"]


def test_every_read_is_a_fresh_request(blender, tmp_path):
    camera = BlenderCamera(blender.port, frames_dir=tmp_path, wait_s=3.0)

    camera.read()
    camera.read()

    assert len(blender.cameras) == 2


def test_a_silent_blender_gives_no_picture_and_no_crash(tmp_path):
    quiet = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    quiet.bind(("127.0.0.1", 0))
    try:
        camera = BlenderCamera(quiet.getsockname()[1], frames_dir=tmp_path, wait_s=0.2)

        assert camera.read() == (False, None)
        assert camera.isOpened()  # the camera is still there: the caller decides when to give up
    finally:
        quiet.close()


def test_release_closes_it(blender, tmp_path):
    camera = BlenderCamera(blender.port, frames_dir=tmp_path, wait_s=0.5)

    camera.release()

    assert camera.isOpened() is False
    assert camera.read() == (False, None)


def test_open_source_understands_blender_names():
    camera = vision.open_source("blender:8767")

    assert isinstance(camera, BlenderCamera)
    camera.release()


@pytest.mark.parametrize("bad", ["blender:", "blender:abc", "blender:0", "blender:70000"])
def test_a_bad_blender_port_is_refused(bad):
    with pytest.raises(ValueError):
        vision.open_source(bad)


def test_each_process_uses_its_own_picture_file_so_two_readers_never_share_one(blender, tmp_path):
    import os

    camera = BlenderCamera(blender.port, frames_dir=tmp_path, wait_s=3.0)
    camera.read()

    assert (tmp_path / f"topdown_view_{os.getpid()}.png").exists()
