"""Tests for the frame source that reconnects when a network camera drops out."""

import numpy as np
import pytest

from stream import FrameSource


def picture(value=0):
    return np.full((2, 2, 3), value, dtype=np.uint8)


class FakeCapture:
    """Hands out its pictures once, then fails every read, like a stream that went quiet."""

    def __init__(self, pictures=(), opened=True):
        self._pictures = list(pictures)
        self._opened = opened
        self.released = False

    def isOpened(self):
        return self._opened

    def read(self):
        if self._opened and self._pictures:
            return True, self._pictures.pop(0)
        return False, None

    def release(self):
        self.released = True


class FakeOpener:
    """Returns the prepared captures in order, then captures that cannot open."""

    def __init__(self, *captures):
        self._captures = list(captures)
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return self._captures.pop(0) if self._captures else FakeCapture(opened=False)


def source_for(*captures, **kwargs):
    delays = []
    opener = FakeOpener(*captures)
    options = {"max_failed_reads": 2, "max_reconnects": 3, "retry_delay_s": 0.5}
    options.update(kwargs)
    source = FrameSource(opener, sleep=delays.append, **options)
    return source, opener, delays


def test_pictures_come_through_in_order():
    source, _, _ = source_for(FakeCapture([picture(1), picture(2)]))

    assert source.read()[0, 0, 0] == 1
    assert source.read()[0, 0, 0] == 2
    assert not source.gave_up


def test_a_few_failed_reads_do_not_drop_the_connection():
    source, opener, _ = source_for(FakeCapture([picture(1)]))

    assert source.read() is not None
    assert source.read() is None  # failure 1
    assert source.read() is None  # failure 2, still within the limit

    assert opener.calls == 1
    assert not source.gave_up


def test_too_many_failed_reads_reopen_the_stream_and_pictures_resume():
    first = FakeCapture([picture(1)])
    second = FakeCapture([picture(9)])
    source, opener, delays = source_for(first, second)

    assert source.read() is not None
    assert [source.read() for _ in range(3)] == [None, None, None]  # the 3rd one reconnects
    resumed = source.read()

    assert resumed[0, 0, 0] == 9
    assert opener.calls == 2
    assert first.released
    assert delays == [0.5]


def test_it_gives_up_after_too_many_failed_reconnects():
    source, opener, delays = source_for()  # nothing ever opens

    for _ in range(10):
        source.read()

    assert source.gave_up
    assert opener.calls == 1 + 3  # the first open, then three reconnects
    assert delays == [0.5, 0.5, 0.5]
    assert source.read() is None


def test_a_stream_that_never_opens_at_the_start_is_retried():
    source, opener, _ = source_for(FakeCapture(opened=False), FakeCapture([picture(5)]))

    pictures = [source.read() for _ in range(3)]

    assert any(p is not None and p[0, 0, 0] == 5 for p in pictures)
    assert opener.calls == 2


def test_a_good_picture_gives_the_retries_back():
    outage_one = FakeCapture([picture(1)])
    outage_two = FakeCapture([picture(2)])
    source, _, _ = source_for(
        FakeCapture([picture(0)]), outage_one, outage_two, max_reconnects=1
    )

    seen = []
    for _ in range(30):
        frame = source.read()
        if frame is not None:
            seen.append(int(frame[0, 0, 0]))
        if len(seen) == 3:
            break  # stop here: after the last picture the stream goes quiet for good

    assert seen == [0, 1, 2]  # it recovered twice although it only allows one retry in a row
    assert not source.gave_up


def test_closing_releases_the_stream():
    capture = FakeCapture([picture(1)])
    source, _, _ = source_for(capture)

    source.close()

    assert capture.released


@pytest.mark.parametrize(
    "kwargs", [{"max_failed_reads": 0}, {"max_reconnects": -1}, {"retry_delay_s": -0.1}]
)
def test_nonsense_settings_are_rejected(kwargs):
    with pytest.raises(ValueError):
        source_for(FakeCapture(), **kwargs)
