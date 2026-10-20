"""Asking the Blender twin for a picture and waiting for it."""

import json
import socket
import threading

import cv2
import numpy as np

from snapshot_client import request_picture
from snapshot_protocol import parse_snapshot




class Answerer(threading.Thread):
    """Plays Blender: answers snapshot requests with a small picture and a sidecar, until stopped."""

    def __init__(self, frames_dir, sidecar=None):
        super().__init__(daemon=True)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.settimeout(0.1)
        self.port = self.sock.getsockname()[1]
        self.frames_dir = frames_dir
        self.sidecar = sidecar if sidecar is not None else {"camera": "topdown"}
        self.stop = False

    def run(self):
        while not self.stop:
            try:
                raw, _ = self.sock.recvfrom(4096)
            except OSError:
                continue
            request = parse_snapshot(json.loads(raw), self.frames_dir)
            if request is not None:
                cv2.imwrite(str(request.path), np.full((48, 64, 3), 77, dtype=np.uint8))
                request.path.with_suffix(".json").write_text(json.dumps(self.sidecar), encoding="utf-8")


def test_request_picture_returns_the_picture_and_its_sidecar(tmp_path):
    answerer = Answerer(tmp_path, {"camera": "topdown", "survivor_box": None})
    answerer.start()
    try:
        result = request_picture(tmp_path / "view.png", "topdown", "127.0.0.1", answerer.port, wait_s=3.0)
    finally:
        answerer.stop = True

    image, sidecar = result
    assert image.shape == (48, 64, 3)
    assert sidecar == {"camera": "topdown", "survivor_box": None}


def test_request_picture_gives_none_when_nobody_answers(tmp_path):
    quiet = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    quiet.bind(("127.0.0.1", 0))
    try:
        assert request_picture(tmp_path / "v.png", "rover", "127.0.0.1", quiet.getsockname()[1], wait_s=0.2) is None
    finally:
        quiet.close()


def test_request_picture_never_returns_an_older_picture(tmp_path):
    cv2.imwrite(str(tmp_path / "v.png"), np.zeros((4, 4, 3), dtype=np.uint8))
    (tmp_path / "v.json").write_text("{}", encoding="utf-8")
    quiet = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    quiet.bind(("127.0.0.1", 0))
    try:
        assert request_picture(tmp_path / "v.png", "rover", "127.0.0.1", quiet.getsockname()[1], wait_s=0.2) is None
    finally:
        quiet.close()


def test_a_picture_file_another_program_is_holding_does_not_crash_the_request(tmp_path, monkeypatch):
    from pathlib import Path

    def locked(self, missing_ok=False):
        raise PermissionError("in use by another process")

    monkeypatch.setattr(Path, "unlink", locked)
    quiet = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    quiet.bind(("127.0.0.1", 0))
    try:
        assert request_picture(tmp_path / "v.png", "rover", "127.0.0.1", quiet.getsockname()[1], wait_s=0.2) is None
    finally:
        quiet.close()
