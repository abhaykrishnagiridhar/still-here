"""The operator server: pages, the video, and the buttons."""

from types import SimpleNamespace

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

import server
from models import Block
from route import route

BOUNDS = (-10.0, -100.0, 320.0, 100.0)
WALL = [Block(i, i, 150.0, float(y), 1) for i, y in enumerate((-80, -40, 0, 40, 80), start=1)]
LOCAL = {"origin": "http://127.0.0.1:8000"}
OUTSIDE = {"origin": "https://evil.example"}


def seen(blocks=WALL, survivor_px=(320, 100)):
    result = route(blocks, [], (0.0, 0.0), (300.0, 0.0), bounds=BOUNDS)
    scene = SimpleNamespace(blocks=tuple(blocks))
    return SimpleNamespace(result=result, survivor=survivor_px, px_per_mm=2.0, scene=scene)


class ReportRecorder:
    def __init__(self):
        self.calls = []

    def __call__(self, facts, path, summary):
        self.calls.append((facts, path, summary))


@pytest.fixture
def written():
    return ReportRecorder()


@pytest.fixture
def app(written):
    return server.create_app(source=None, report_writer=written)


@pytest.fixture
def client(app):
    return TestClient(app)


def feed(app, observation=None):
    app.state.operator.observe(observation or seen())


def plan_key(client):
    return client.get("/api/state").json()["plan"]["key"]


# --- pages ----------------------------------------------------------------------------


def test_the_root_goes_to_the_autonomous_page(client):
    response = client.get("/", follow_redirects=False)

    assert response.status_code in (302, 307)
    assert response.headers["location"] == "/autonomous.html"


def test_the_listed_pages_and_assets_are_served(client):
    for name in ("autonomous.html", "index.html", "landing.css", "operator.js", "operator.css"):
        assert client.get(f"/{name}").status_code == 200, name


def test_files_that_are_not_listed_are_not_served(client):
    for name in ("config.example.toml", "config.toml", "server.py", "../README.md", "pyproject.toml"):
        assert client.get(f"/{name}").status_code == 404, name


# --- state and report -----------------------------------------------------------------


def test_the_state_starts_with_nothing_seen(client):
    state = client.get("/api/state").json()

    assert state["phase"] == "scanning"
    assert state["frame"] == {"w": 640, "h": 480}


def test_the_state_shows_the_plan_once_the_camera_has_one(app, client):
    feed(app)

    state = client.get("/api/state").json()

    assert state["phase"] == "plan_ready"
    assert state["can_approve"] is True
    assert state["plan"]["order"]


def test_the_report_before_any_run_says_so(client):
    body = client.get("/api/report").json()

    assert body["report"]["outcome"] == "not_run"
    assert "no run" in body["text"].lower()


# --- the buttons ----------------------------------------------------------------------


def test_tapping_the_survivor_stores_the_spot(app, client):
    response = client.post("/api/survivor", json={"x": 320.4, "y": 99.6}, headers=LOCAL)

    assert response.status_code == 200
    assert app.state.operator.survivor_hint == (320, 100)


def test_clearing_the_survivor_forgets_it(app, client):
    client.post("/api/survivor", json={"x": 1, "y": 2}, headers=LOCAL)

    client.post("/api/survivor/clear", headers=LOCAL)

    assert app.state.operator.survivor_hint is None


def test_a_tap_outside_the_picture_is_refused(client):
    for body in ({"x": -5, "y": 10}, {"x": 700, "y": 10}, {"x": 10, "y": 500}, {"x": "a", "y": 1}, {}):
        assert client.post("/api/survivor", json=body, headers=LOCAL).status_code == 422, body


def test_approving_the_shown_plan_sends_it_to_the_rover(app, client):
    feed(app)

    response = client.post("/api/approve", json={"key": plan_key(client)}, headers=LOCAL)

    assert response.status_code == 200
    assert client.get("/api/state").json()["phase"] == "waiting"


def test_approving_a_plan_that_is_not_the_shown_one_is_refused(app, client):
    feed(app)

    response = client.post("/api/approve", json={"key": "stale"}, headers=LOCAL)

    assert response.status_code == 409
    assert "changed" in response.json()["detail"].lower()


def test_abort_stops_the_run(app, client):
    feed(app)
    client.post("/api/approve", json={"key": plan_key(client)}, headers=LOCAL)

    client.post("/api/abort", headers=LOCAL)

    assert client.get("/api/state").json()["phase"] == "aborted"


def test_a_page_from_another_site_cannot_press_any_button(app, client):
    feed(app)
    key = plan_key(client)

    for path, body in (
        ("/api/approve", {"key": key}),
        ("/api/abort", None),
        ("/api/survivor", {"x": 10, "y": 10}),
        ("/api/survivor/clear", None),
        ("/api/reset", None),
    ):
        response = client.post(path, json=body, headers=OUTSIDE)
        assert response.status_code == 403, path
    assert client.get("/api/state").json()["phase"] == "plan_ready"


def test_reading_state_from_another_site_is_not_allowed_either(client):
    assert client.get("/api/state", headers=OUTSIDE).status_code == 403


def test_reset_starts_a_fresh_run(app, client):
    feed(app)
    client.post("/api/approve", json={"key": plan_key(client)}, headers=LOCAL)

    client.post("/api/reset", headers=LOCAL)

    assert client.get("/api/state").json()["phase"] == "scanning"


# --- a whole run through the simulated rover -----------------------------------------


def run_the_plan(app, client, until):
    for _ in range(2000):
        app.state.advance(0.05)
        if client.get("/api/state").json()["phase"] == until:
            return
    raise AssertionError(f"never reached {until}")


def test_an_approved_plan_runs_on_the_simulated_rover_and_waits_for_the_camera(app, client):
    feed(app)
    client.post("/api/approve", json={"key": plan_key(client)}, headers=LOCAL)

    run_the_plan(app, client, "verifying")

    state = client.get("/api/state").json()
    assert state["progress"]["done"] == state["progress"]["total"] > 0
    assert state["verified"] is None


def test_a_clear_camera_picture_finishes_the_run_and_the_report_is_written_once(app, client, written):
    feed(app)
    client.post("/api/approve", json={"key": plan_key(client)}, headers=LOCAL)
    run_the_plan(app, client, "verifying")

    for _ in range(3):
        feed(app, seen([]))
    app.state.advance(0.05)
    app.state.advance(0.05)

    state = client.get("/api/state").json()
    assert state["phase"] == "done" and state["verified"] is True
    assert len(written.calls) == 1
    facts, path, summary = written.calls[0]
    assert facts["status"] == "completed" and facts["steps_completed"] == facts["steps_planned"]
    assert path.endswith("safe_path_report.json")
    assert summary == "Run completed and verified."
    report = client.get("/api/report").json()
    assert all(item["ok"] for item in report["report"]["picked"])
    assert "moved out of the way" in report["text"]
    assert "Summary: Run completed and verified." in report["text"]


def test_an_aborted_run_writes_a_safe_stop_report(app, client, written):
    feed(app)
    client.post("/api/approve", json={"key": plan_key(client)}, headers=LOCAL)

    client.post("/api/abort", headers=LOCAL)
    app.state.advance(0.05)

    assert [c[0]["status"] for c in written.calls] == ["aborted"]
    assert written.calls[0][2] == "Run stopped for safety."


# --- the camera side ------------------------------------------------------------------


def red_blocks_frame():
    image = np.zeros((480, 640, 3), dtype=np.uint8)
    for cx, cy in ((150, 200), (300, 300), (450, 200)):
        cv2.rectangle(image, (cx - 30, cy - 30), (cx + 30, cy + 30), (0, 0, 255), -1)
    return image


def test_a_camera_frame_updates_the_operator_and_the_video(app, client):
    for i in range(60):
        app.state.capture.process(red_blocks_frame(), i / 30.0)

    state = client.get("/api/state").json()
    assert state["phase"] == "need_survivor"
    jpeg = app.state.capture.latest_jpeg()
    assert jpeg[:2] == b"\xff\xd8"
    assert cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR).shape == (480, 640, 3)


def test_the_tapped_survivor_reaches_the_pipeline(app, client):
    client.post("/api/survivor", json={"x": 320, "y": 100}, headers=LOCAL)

    for i in range(60):
        app.state.capture.process(red_blocks_frame(), i / 30.0)

    assert client.get("/api/state").json()["survivor_px"] == [320, 100]


def test_the_video_stream_is_a_series_of_jpeg_parts():
    frames = iter([b"\xff\xd8one", b"\xff\xd8two"])
    stops = iter([False, False, True])

    chunks = list(server.mjpeg_chunks(lambda: next(frames), lambda: next(stops), lambda: None))

    assert len(chunks) == 2
    assert chunks[0].startswith(b"--frame\r\nContent-Type: image/jpeg\r\n")
    assert chunks[0].endswith(b"\xff\xd8one\r\n")


def test_the_video_route_is_there(app):
    assert "/video" in {r.path for r in app.routes}


def test_a_source_that_is_given_starts_nothing_until_run(tmp_path):
    app = server.create_app(source=str(tmp_path / "nothing.avi"))

    assert app.state.source == str(tmp_path / "nothing.avi")
