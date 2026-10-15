"""Contract tests for the browser-to-Blender gyro bridge."""

import json
import socket

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import phone_bridge


def test_phone_page_keeps_arm_controls_out_of_drive_mode():
    page = (phone_bridge.Path(__file__).with_name("phone_control.html")).read_text(encoding="utf-8")

    assert 'id="arm-controls" hidden' in page
    assert 'armControls.hidden = mode !== \'arm\'' in page
    assert 'role="tablist"' in page


def test_phone_page_has_a_compact_brand_and_mobile_safety_treatments():
    page = (phone_bridge.Path(__file__).with_name("phone_control.html")).read_text(encoding="utf-8")

    assert 'class="brand"' in page
    assert 'viewport-fit=cover' in page
    assert '@media (prefers-reduced-motion: reduce)' in page
    assert 'env(safe-area-inset-bottom)' in page


def test_a_drive_sample_becomes_a_smoothed_wheel_command_after_calibration():
    bridge = phone_bridge.PhoneBridge()
    bridge.handle({"beta": 0, "gamma": 0, "mode": "drive"}, now=0.9)

    packet = bridge.handle({"beta": -30, "gamma": 0, "mode": "drive"}, now=1.0)

    assert packet["kind"] == "command"
    assert packet["message"] == {"type": "drive", "left": 0.25, "right": 0.25}


def test_an_arm_sample_contains_the_protocol_arm_pose():
    bridge = phone_bridge.PhoneBridge()
    bridge.handle({"beta": 0, "gamma": 0, "mode": "drive"}, now=1.0)

    packet = bridge.handle(
        {"beta": 0, "gamma": 0, "mode": "arm", "elbow": -80, "grip": False}, now=1.1
    )

    assert packet["message"]["type"] == "arm_pose"
    assert packet["message"]["elbow"] == -80.0
    assert packet["message"]["gripper"] == 0.0


def test_bad_phone_payload_is_rejected_without_emitting_a_command():
    bridge = phone_bridge.PhoneBridge()

    assert bridge.handle({"beta": "not-a-number"}, now=1.0) is None


def test_mode_change_keeps_the_stop_packet_before_the_arm_packet():
    bridge = phone_bridge.PhoneBridge()
    bridge.handle_all({"beta": 0, "gamma": 0, "mode": "drive"}, now=1.0)

    packets = bridge.handle_all({"beta": 0, "gamma": 0, "mode": "arm"}, now=1.1)

    assert [packet["message"]["type"] for packet in packets] == ["drive", "arm_pose"]
    assert packets[0]["message"]["left"] == 0.0
    assert packets[0]["message"]["right"] == 0.0


def test_idle_emits_one_safe_stop_after_phone_data_goes_stale():
    bridge = phone_bridge.PhoneBridge()
    bridge.handle_all({"beta": -20, "gamma": 0, "mode": "drive"}, now=1.0)

    assert bridge.idle(now=1.6) == [
        {"kind": "command", "message": {"type": "drive", "left": 0.0, "right": 0.0}}
    ]
    assert bridge.idle(now=2.0) == []


# --- who may drive the rover: the origin rule must survive page changes -------------------------


@pytest.mark.parametrize(
    "origin",
    [None, "", "http://localhost:3000", "http://127.0.0.1:8765", "http://192.168.0.20:8765", "http://10.0.0.5"],
)
def test_pages_from_this_machine_or_the_local_network_are_allowed(origin):
    assert phone_bridge.origin_allowed(origin)


@pytest.mark.parametrize("origin", ["https://evil.example", "http://8.8.8.8", "http://localhost.evil.example", "null"])
def test_pages_from_the_internet_are_refused(origin):
    assert not phone_bridge.origin_allowed(origin)


def test_the_socket_closes_a_browser_page_from_another_site():
    client = TestClient(phone_bridge.app)

    with pytest.raises(WebSocketDisconnect) as refused:
        with client.websocket_connect("/phone", headers={"origin": "https://evil.example"}):
            pass

    assert refused.value.code == 1008


def test_the_socket_accepts_a_page_from_the_local_network():
    client = TestClient(phone_bridge.app)

    with client.websocket_connect("/phone", headers={"origin": "http://192.168.0.20:8765"}) as ws:
        ws.send_text("not json")


def test_the_phone_page_is_served_over_plain_http():
    response = TestClient(phone_bridge.app).get("/")

    assert response.status_code == 200
    assert "new WebSocket" in response.text
    assert "certificate" not in response.text.lower()


# --- what actually reaches Blender: bad input must fail closed ------------------------------------

STOP = {"kind": "command", "message": {"type": "drive", "left": 0.0, "right": 0.0}}
LOCAL = {"origin": "http://127.0.0.1:8765"}


@pytest.fixture
def blender(monkeypatch):
    """A fake Blender: a UDP socket that receives whatever the bridge sends."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    listener.bind(("127.0.0.1", 0))
    monkeypatch.setattr(phone_bridge, "BLENDER_PORT", listener.getsockname()[1])
    yield listener
    listener.close()


def received(listener, quiet=0.4):
    packets = []
    listener.settimeout(quiet)
    while True:
        try:
            raw, _ = listener.recvfrom(4096)
        except socket.timeout:
            return packets
        packets.append(json.loads(raw))


def moving(packet):
    message = packet["message"]
    return message["type"] == "drive" and (message["left"] != 0.0 or message["right"] != 0.0)


def test_bad_samples_never_make_the_rover_move_and_do_not_end_the_connection(blender):
    client = TestClient(phone_bridge.app)

    with client.websocket_connect("/phone", headers=LOCAL) as ws:
        ws.send_text(json.dumps({"beta": 0, "gamma": 0, "mode": "drive", "calibrate": True}))
        ws.send_text('{"beta": NaN, "gamma": 0, "mode": "drive"}')
        ws.send_text('{"beta": Infinity, "gamma": 0, "mode": "drive"}')
        ws.send_text(json.dumps({"beta": 0, "gamma": 0, "mode": "arm", "elbow": "bent"}))
        ws.send_text("[1, 2, 3]")
        ws.send_text('"just text"')
        ws.send_text(json.dumps({"beta": 0, "gamma": 0, "mode": "drive"}))  # still accepted afterwards

    packets = received(blender)
    assert not any(moving(p) for p in packets)
    assert packets[-1] == STOP


def test_the_wheels_are_stopped_whatever_ends_the_connection(blender, monkeypatch):
    def explode(self, sample, now):
        raise RuntimeError("boom")

    monkeypatch.setattr(phone_bridge.PhoneBridge, "handle_all", explode)
    client = TestClient(phone_bridge.app)

    with pytest.raises(RuntimeError, match="boom"):
        with client.websocket_connect("/phone", headers=LOCAL) as ws:
            ws.send_text(json.dumps({"beta": 0, "gamma": 0}))
            ws.receive_text()

    assert received(blender)[-1] == STOP


def test_a_clean_disconnect_still_sends_one_stop(blender):
    client = TestClient(phone_bridge.app)

    with client.websocket_connect("/phone", headers=LOCAL) as ws:
        ws.send_text(json.dumps({"beta": 0, "gamma": 0, "mode": "drive", "calibrate": True}))

    assert received(blender)[-1] == STOP
