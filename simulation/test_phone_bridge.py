"""Contract tests for the browser-to-Blender gyro bridge."""

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import phone_bridge


def test_a_drive_sample_becomes_a_normalised_wheel_command():
    bridge = phone_bridge.PhoneBridge()
    bridge.handle({"beta": 0, "gamma": 0, "mode": "drive"}, now=0.9)  # the first sample sets the centre

    for i in range(30):  # hold the tilt: the phone smoothing needs a moment to settle
        packet = bridge.handle({"beta": -30, "gamma": 0, "mode": "drive"}, now=1.0 + i * 0.05)

    assert packet["kind"] == "command"
    assert packet["message"]["type"] == "drive"
    assert packet["message"]["left"] == pytest.approx(1.0, abs=0.01)
    assert packet["message"]["right"] == pytest.approx(1.0, abs=0.01)


def test_an_arm_sample_contains_the_protocol_arm_pose():
    bridge = phone_bridge.PhoneBridge()
    bridge.handle({"beta": 0, "gamma": 0, "mode": "drive"}, now=1.0)

    packet = bridge.handle(
        {"beta": 0, "gamma": 0, "mode": "arm", "elbow": -80, "grip": False}, now=1.1
    )

    assert packet["message"]["type"] == "arm_pose"
    assert packet["message"]["elbow"] == -80.0
    assert packet["message"]["gripper"] == 0.0


@pytest.mark.parametrize(
    "origin",
    [None, "", "http://localhost:3000", "http://127.0.0.1:8765", "http://192.168.0.20:8765",
     "http://10.0.0.5", "http://[::1]:8765"],
)
def test_pages_from_this_machine_or_the_local_network_are_allowed(origin):
    assert phone_bridge.origin_allowed(origin)


@pytest.mark.parametrize(
    "origin",
    ["https://evil.example", "http://8.8.8.8", "http://localhost.evil.example", "null", "http://"],
)
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
    assert "WebSocket" in response.text
    assert "certificate" not in response.text.lower()


def test_bad_phone_payload_is_rejected_without_emitting_a_command():
    bridge = phone_bridge.PhoneBridge()

    assert bridge.handle({"beta": "not-a-number"}, now=1.0) is None
