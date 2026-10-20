"""The rover link to the Blender twin: commands out over UDP, the rover's messages back."""

import json
import socket
import time

import pytest

from blender_link import BlenderLink


class FakeBlender:
    """A UDP socket standing where blender_rover.py listens."""

    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.settimeout(1.0)
        self.port = self.sock.getsockname()[1]
        self.peer = None

    def receive(self):
        raw, self.peer = self.sock.recvfrom(65535)
        return json.loads(raw)

    def reply(self, message):
        self.sock.sendto(json.dumps({"kind": "rover", "message": message}).encode(), self.peer)

    def close(self):
        self.sock.close()


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


@pytest.fixture
def blender():
    fake = FakeBlender()
    yield fake
    fake.close()


def make(blender, clock=None):
    return BlenderLink(blender.port, clock=clock or Clock())


def pump(link, wanted=1, tries=100):
    """Advance until enough has come back (a datagram needs a moment to arrive)."""
    out = []
    for _ in range(tries):
        out += link.advance(0.0)
        if len(out) >= wanted:
            break
        time.sleep(0.01)
    return out


def test_a_command_goes_out_wrapped_and_marked_for_a_reply(blender):
    link = make(blender)
    try:
        link.send({"type": "plan_start", "plan_id": 3})

        packet = blender.receive()

        assert packet == {"kind": "command", "reply": True, "message": {"type": "plan_start", "plan_id": 3}}
    finally:
        link.close()


def test_what_the_rover_says_comes_back_from_advance(blender):
    link = make(blender)
    try:
        link.send({"type": "ping", "t": 0})
        blender.receive()
        blender.reply({"type": "state", "plan_id": 3})
        blender.reply({"type": "event", "code": "plan_stored"})

        assert pump(link, wanted=2) == [{"type": "state", "plan_id": 3}, {"type": "event", "code": "plan_stored"}]
    finally:
        link.close()


def test_it_is_not_connected_until_blender_answers_and_not_after_it_goes_quiet(blender):
    clock = Clock()
    link = make(blender, clock)
    try:
        assert link.connected is False

        link.send({"type": "ping", "t": 0})
        blender.receive()
        blender.reply({"type": "state"})
        assert pump(link)
        assert link.connected is True

        clock.now += 2.5
        assert link.connected is False
    finally:
        link.close()


def test_it_pings_every_half_second_so_the_rover_does_not_think_the_link_died(blender):
    link = make(blender)
    try:
        link.advance(0.6)

        packet = blender.receive()

        assert packet["message"]["type"] == "ping" and packet["reply"] is True
    finally:
        link.close()


def test_it_does_not_ping_again_straight_away(blender):
    link = make(blender)
    try:
        link.advance(0.6)
        blender.receive()
        link.advance(0.1)

        blender.sock.settimeout(0.1)
        with pytest.raises(socket.timeout):
            blender.receive()
    finally:
        link.close()


@pytest.mark.parametrize(
    "junk", [b"not json", b"[]", b'{"kind": "other"}', b'{"kind": "rover"}', b'{"kind": "rover", "message": 5}']
)
def test_garbage_from_the_port_is_ignored(blender, junk):
    link = make(blender)
    try:
        link.send({"type": "ping", "t": 0})
        blender.receive()
        blender.sock.sendto(junk, blender.peer)
        blender.reply({"type": "state"})

        assert pump(link) == [{"type": "state"}]
    finally:
        link.close()


def test_a_closed_link_reports_an_error_instead_of_crashing(blender):
    link = make(blender)
    link.close()

    link.send({"type": "ping", "t": 0})

    assert link.last_error
    assert link.advance(0.1) == []


def test_it_names_where_it_is_talking_to(blender):
    link = make(blender)
    try:
        assert str(blender.port) in link.address
    finally:
        link.close()
