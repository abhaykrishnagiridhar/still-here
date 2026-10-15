"""The software rover as a WebSocket server."""

import json
import time

import pytest
from websockets.exceptions import ConnectionClosed, InvalidStatus
from websockets.sync.client import connect

import sim_server
from models import Block
from sim_server import BUSY_CODE, SimRoverServer

PICK = {"id": 1, "action": "pick", "x": 150, "y": 0, "z": 20}


@pytest.fixture
def rover():
    server = SimRoverServer([Block(1, 1, 150.0, 0.0, 1)], speed=1.0).start()
    yield server
    server.close()


def url(server):
    return f"ws://127.0.0.1:{server.port}"


def messages(ws, seconds=1.0):
    """Everything the rover sends in the next `seconds` (it sends state every 0.2 s, so it never goes quiet)."""
    out = []
    deadline = time.monotonic() + seconds
    while (left := deadline - time.monotonic()) > 0:
        try:
            out.append(json.loads(ws.recv(timeout=left)))
        except TimeoutError:
            break
    return out


def test_the_rover_sends_its_state_to_a_connected_operator(rover):
    with connect(url(rover)) as ws:
        ws.send(json.dumps({"type": "ping", "t": 0}))

        got = messages(ws, 1.0)

    assert any(m["type"] == "state" for m in got)


def test_a_plan_is_stored_and_confirmed(rover):
    with connect(url(rover)) as ws:
        ws.send(json.dumps({"type": "plan", "plan_id": 3, "steps": [PICK]}))

        got = messages(ws, 1.0)

    assert any(m.get("code") == "plan_stored" for m in got)
    assert any(m["type"] == "state" and m["plan_id"] == 3 for m in got)


def test_the_rovers_state_survives_the_operator_reconnecting(rover):
    with connect(url(rover)) as ws:
        ws.send(json.dumps({"type": "plan", "plan_id": 5, "steps": [PICK]}))
        messages(ws, 0.5)

    with connect(url(rover)) as ws:
        got = messages(ws, 1.0)

    assert any(m["type"] == "state" and m["plan_id"] == 5 for m in got)


def test_unreadable_messages_are_ignored_and_the_connection_stays_up(rover):
    with connect(url(rover)) as ws:
        for junk in ("not json", "[1, 2]", '"text"', "null", "42"):
            ws.send(junk)
        ws.send(json.dumps({"type": "ping", "t": 1}))

        got = messages(ws, 1.0)

    assert any(m["type"] == "state" for m in got)


def test_a_page_from_another_website_is_refused(rover):
    with pytest.raises(InvalidStatus) as refused:
        connect(url(rover), origin="https://evil.example")

    assert refused.value.response.status_code == 403


def test_pages_from_this_machine_and_the_local_network_are_allowed(rover):
    for origin in ("http://127.0.0.1:8000", "http://192.168.0.20:8000", "http://localhost:8000"):
        with connect(url(rover), origin=origin) as ws:
            ws.send(json.dumps({"type": "ping", "t": 0}))
            assert any(m["type"] == "state" for m in messages(ws, 1.0))


def test_a_second_operator_is_turned_away_while_one_is_driving(rover):
    with connect(url(rover)) as first:
        first.send(json.dumps({"type": "ping", "t": 0}))
        messages(first, 0.5)

        with connect(url(rover)) as second:
            with pytest.raises(ConnectionClosed) as closed:
                second.recv(timeout=2)

    assert closed.value.rcvd.code == BUSY_CODE


def test_the_next_operator_can_connect_once_the_first_has_left(rover):
    with connect(url(rover)) as first:
        first.send(json.dumps({"type": "ping", "t": 0}))
        messages(first, 0.3)

    with connect(url(rover)) as second:
        second.send(json.dumps({"type": "ping", "t": 0}))
        assert any(m["type"] == "state" for m in messages(second, 1.0))


def test_a_faster_speed_runs_the_rovers_clock_faster():
    fast = SimRoverServer(speed=10.0).start()
    try:
        with connect(url(fast)) as ws:
            ws.send(json.dumps({"type": "ping", "t": 0}))
            messages(ws, 1.0)
        assert fast.rover.t > 4.0  # about a second of waiting is several seconds of rover time
    finally:
        fast.close()


# --- the command line --------------------------------------------------------------------------


def test_the_command_refuses_a_speed_that_is_not_positive(capsys):
    assert sim_server.main(["--speed", "0"]) == 1
    assert "--speed" in capsys.readouterr().err


def test_the_command_reports_a_missing_scenario_file(tmp_path, capsys):
    assert sim_server.main(["--scenario", str(tmp_path / "none.json"), "--port", "0"]) == 1
    assert "none.json" in capsys.readouterr().err


def test_the_command_reports_a_port_that_is_taken(capsys):
    held = SimRoverServer().start()
    try:
        assert sim_server.main(["--port", str(held.port)]) == 1
        assert "Could not start" in capsys.readouterr().err
    finally:
        held.close()
