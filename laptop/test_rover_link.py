"""The server's link to the real rover, tested against the software rover over a real WebSocket."""

import json
import threading
import time

import pytest
from websockets.sync.server import serve

from models import Block
from rover_link import RealLink
from sim_server import SimRoverServer

PICK = {"id": 1, "action": "pick", "x": 150, "y": 0, "z": 20}


def wait_until(condition, seconds=5.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.02)
    return False


def collect(link, seconds):
    """Everything the link receives over the next `seconds`."""
    out = []
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        out += link.advance(0.05)
        time.sleep(0.02)
    return out


@pytest.fixture
def rover():
    server = SimRoverServer([Block(1, 1, 150.0, 0.0, 1)]).start()
    yield server
    server.close()


@pytest.fixture
def link(rover):
    connection = RealLink("127.0.0.1", rover.port, retry_s=0.2).start()
    yield connection
    connection.close()


def test_the_link_connects_to_the_rover(link):
    assert wait_until(lambda: link.connected)
    assert link.address.startswith("ws://127.0.0.1:")


def test_the_rover_s_messages_arrive_through_advance(link):
    assert wait_until(lambda: link.connected)

    got = collect(link, 1.0)

    assert any(m["type"] == "state" for m in got)


def test_a_plan_sent_through_the_link_is_stored_by_the_rover(link):
    assert wait_until(lambda: link.connected)

    assert link.send({"type": "plan", "plan_id": 4, "steps": [PICK]}) is True
    got = collect(link, 1.0)

    assert any(m.get("code") == "plan_stored" for m in got)
    assert any(m["type"] == "state" and m["plan_id"] == 4 for m in got)


def test_the_link_pings_so_the_rover_never_thinks_the_link_was_lost():
    fast = SimRoverServer(speed=3.0).start()  # the rover's 2 second timeout passes in under a second of waiting
    connection = RealLink("127.0.0.1", fast.port, retry_s=0.2).start()
    try:
        assert wait_until(lambda: connection.connected)

        got = collect(connection, 2.5)

        assert not any(m.get("code") == "link_lost" for m in got)
        assert fast.rover.t > 5  # plenty of rover time passed
    finally:
        connection.close()
        fast.close()


def test_nothing_is_sent_and_false_is_returned_when_the_rover_is_not_connected():
    link = RealLink("127.0.0.1", 1, retry_s=0.2)  # never started

    assert link.connected is False
    assert link.send({"type": "drive", "left": 1, "right": 1}) is False


def test_a_message_that_is_not_a_protocol_message_is_refused_loudly(link):
    assert wait_until(lambda: link.connected)

    for bad in ({"no": "type"}, {"type": 5}, "drive", None):
        with pytest.raises(ValueError):
            link.send(bad)


def test_an_unreachable_rover_is_reported_and_the_link_keeps_trying():
    link = RealLink("127.0.0.1", 1, retry_s=0.1, open_timeout_s=0.5).start()
    try:
        assert wait_until(lambda: link.last_error != "", 5)
        assert link.connected is False
    finally:
        link.close()


def test_a_name_that_does_not_exist_does_not_crash_the_link():
    link = RealLink("no-such-rover.invalid", 81, retry_s=0.1, open_timeout_s=0.5).start()
    try:
        assert wait_until(lambda: link.last_error != "", 8)
        assert link.connected is False
    finally:
        link.close()


def test_the_link_reconnects_by_itself_after_the_rover_goes_away_and_comes_back():
    first = SimRoverServer().start()
    port = first.port
    link = RealLink("127.0.0.1", port, retry_s=0.2).start()
    try:
        assert wait_until(lambda: link.connected)

        first.close()
        assert wait_until(lambda: not link.connected, 5)
        assert link.send({"type": "drive", "left": 1, "right": 1}) is False  # nothing is held back for later

        second = SimRoverServer(port=port).start()
        try:
            assert wait_until(lambda: link.connected, 8)
            assert any(m["type"] == "state" for m in collect(link, 1.0))
        finally:
            second.close()
    finally:
        link.close()


def test_closing_the_link_disconnects_it(rover):
    link = RealLink("127.0.0.1", rover.port, retry_s=0.2).start()
    assert wait_until(lambda: link.connected)

    link.close()

    assert link.connected is False


def test_garbage_from_the_other_end_is_ignored_and_real_messages_still_arrive():
    def talk(connection):
        for junk in ("not json", "[1, 2]", '{"no": "type"}', '{"type": 7}', "null"):
            connection.send(junk)
        connection.send(json.dumps({"type": "event", "code": "hello", "detail": ""}))
        try:
            while True:
                connection.recv(timeout=0.2)
        except Exception:
            return

    server = serve(talk, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    link = RealLink("127.0.0.1", server.socket.getsockname()[1], retry_s=0.2).start()
    try:
        assert wait_until(lambda: link.connected)

        got = collect(link, 0.8)

        assert [m["code"] for m in got if m["type"] == "event"][:1] == ["hello"]
        assert all(isinstance(m.get("type"), str) for m in got)
    finally:
        link.close()
        server.shutdown()


def test_a_custom_opener_is_used_for_the_connection():
    attempts = []

    def failing_opener(url, open_timeout):
        attempts.append(url)
        raise OSError("refused")

    link = RealLink("rover.test", 81, retry_s=0.05, opener=failing_opener).start()
    try:
        assert wait_until(lambda: len(attempts) >= 2, 3)
        assert attempts[0] == "ws://rover.test:81"
        assert "refused" in link.last_error
    finally:
        link.close()
