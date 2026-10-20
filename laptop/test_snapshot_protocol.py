"""The request that asks Blender for a picture, and the checks that keep it from writing anywhere it likes."""

import json
from pathlib import Path

import pytest

from snapshot_protocol import CAMERAS, Snapshot, parse_snapshot, snapshot_packet


def test_a_snapshot_packet_is_a_json_datagram_of_the_agreed_shape(tmp_path):
    packet = snapshot_packet(tmp_path / "view.png", camera="rover")

    body = json.loads(packet.decode("utf-8"))
    assert body["kind"] == "snapshot"
    assert body["camera"] == "rover"
    assert body["path"].endswith("view.png")


def test_a_good_request_inside_the_frames_folder_is_accepted(tmp_path):
    packet = json.loads(snapshot_packet(tmp_path / "view.png", camera="overview"))

    request = parse_snapshot(packet, tmp_path)

    assert isinstance(request, Snapshot)
    assert request.camera == "overview"
    assert request.path == (tmp_path / "view.png").resolve()


def test_the_default_camera_is_the_rovers_own(tmp_path):
    request = parse_snapshot({"kind": "snapshot", "path": str(tmp_path / "a.png")}, tmp_path)

    assert request.camera == "rover" and "rover" in CAMERAS


def test_a_path_outside_the_frames_folder_is_refused(tmp_path):
    frames = tmp_path / "frames"
    frames.mkdir()

    assert parse_snapshot({"kind": "snapshot", "path": str(tmp_path / "elsewhere.png")}, frames) is None


def test_a_path_that_climbs_out_with_dots_is_refused(tmp_path):
    frames = tmp_path / "frames"
    frames.mkdir()
    sneaky = str(frames / ".." / "elsewhere.png")

    assert parse_snapshot({"kind": "snapshot", "path": sneaky}, frames) is None


def test_only_png_files_may_be_written(tmp_path):
    assert parse_snapshot({"kind": "snapshot", "path": str(tmp_path / "view.py")}, tmp_path) is None
    assert parse_snapshot({"kind": "snapshot", "path": str(tmp_path / "view")}, tmp_path) is None


def test_an_unknown_camera_is_refused(tmp_path):
    packet = {"kind": "snapshot", "path": str(tmp_path / "a.png"), "camera": "satellite"}

    assert parse_snapshot(packet, tmp_path) is None


@pytest.mark.parametrize(
    "packet",
    [
        {},
        {"kind": "command"},
        {"kind": "snapshot"},
        {"kind": "snapshot", "path": 5},
        {"kind": "snapshot", "path": ""},
        "not a dict",
        None,
    ],
)
def test_malformed_requests_are_ignored(packet, tmp_path):
    assert parse_snapshot(packet, tmp_path) is None


def test_the_top_down_camera_is_known(tmp_path):
    request = parse_snapshot({"kind": "snapshot", "path": str(tmp_path / "t.png"), "camera": "topdown"}, tmp_path)

    assert request is not None and request.camera == "topdown"



def test_the_packet_carries_an_absolute_path_so_blender_cannot_resolve_it_somewhere_else(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    body = json.loads(snapshot_packet("frames/view.png", camera="rover"))

    assert Path(body["path"]).is_absolute()
    assert Path(body["path"]) == (tmp_path / "frames" / "view.png").resolve()
