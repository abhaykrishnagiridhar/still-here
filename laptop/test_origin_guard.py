"""Which web pages may press the operator buttons."""

import pytest

from origin_guard import origin_allowed


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
