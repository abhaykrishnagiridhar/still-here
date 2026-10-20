"""Which web pages may press the operator buttons."""

import pytest

from origin_guard import host_allowed, origin_allowed


@pytest.mark.parametrize(
    "origin",
    [None, "", "http://localhost:8000", "http://127.0.0.1:8000", "http://192.168.0.20:8000",
     "http://10.0.0.5", "http://[::1]:8000"],
)
def test_pages_from_this_machine_or_the_local_network_are_allowed(origin):
    assert origin_allowed(origin)


@pytest.mark.parametrize(
    "origin",
    ["https://evil.example", "http://8.8.8.8", "http://localhost.evil.example", "null", "http://"],
)
def test_pages_from_the_internet_are_refused(origin):
    assert not origin_allowed(origin)


@pytest.mark.parametrize(
    "host",
    ["127.0.0.1:8000", "localhost:8000", "[::1]:8000", "192.168.0.20:8000", "my-laptop:8000", "my-laptop.local:8000"],
)
def test_a_host_header_a_local_page_would_use_is_allowed(host):
    assert host_allowed(host)


@pytest.mark.parametrize("host", [None, "", "evil.example", "evil.example:8000", "a.b.c.example"])
def test_a_public_name_pointed_at_this_laptop_is_refused(host):
    assert not host_allowed(host)
