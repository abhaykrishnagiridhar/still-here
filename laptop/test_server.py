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
    result = route(blocks, [], (0.0, 0.0), (300.0, 0.0), bounds=BOUNDS, corridor=60.0)
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


def test_a_calibration_given_to_the_server_is_used_by_its_camera_pipeline():
    from calibrate import fit

    calibration = fit([[320, 480, 0, 0], [320, 180, 150, 0], [170, 480, 0, 75], [470, 480, 0, -75]])
    app = server.create_app(source=None, calibration=calibration)

    for i in range(60):
        app.state.capture.process(red_blocks_frame(), i / 30.0)

    blocks = app.state.operator.latest_blocks()
    middle = min(blocks, key=lambda b: abs(b.y))
    assert (middle.x, middle.y) == pytest.approx(calibration.to_mm((300, 300)), abs=1.0)


# --- manual control ---------------------------------------------------------------------------


class ManualClock:
    def __init__(self):
        self.now = 10.0

    def __call__(self):
        return self.now


@pytest.fixture
def manual_app(written):
    clock = ManualClock()
    app = server.create_app(source=None, report_writer=written, manual_clock=clock)
    app.state.test_clock = clock
    return app


def wheels(app):
    return app.state.link._rover.wheels


def test_driving_by_hand_moves_the_simulated_wheels(manual_app):
    client = TestClient(manual_app)

    response = client.post("/api/manual/drive", json={"left": 0.5, "right": -0.5}, headers=LOCAL)

    assert response.status_code == 200
    assert wheels(manual_app) == (0.5, -0.5)


def test_the_arm_can_be_moved_by_hand_and_is_held_inside_its_limits(manual_app):
    client = TestClient(manual_app)

    response = client.post(
        "/api/manual/arm", json={"base": 500, "shoulder": 60, "elbow": -90, "gripper": 0}, headers=LOCAL
    )

    assert response.status_code == 200
    assert manual_app.state.link._rover._target["base"] == 90.0


def test_the_wheels_stop_by_themselves_when_the_page_stops_sending(manual_app):
    client = TestClient(manual_app)
    client.post("/api/manual/drive", json={"left": 1, "right": 1}, headers=LOCAL)

    manual_app.state.test_clock.now += 1.0
    manual_app.state.advance(0.05)

    assert wheels(manual_app) == (0.0, 0.0)


def test_the_stop_button_halts_the_wheels(manual_app):
    client = TestClient(manual_app)
    client.post("/api/manual/drive", json={"left": 1, "right": 1}, headers=LOCAL)

    assert client.post("/api/manual/stop", headers=LOCAL).status_code == 200
    assert wheels(manual_app) == (0.0, 0.0)


def test_manual_commands_are_refused_while_an_approved_plan_runs(manual_app):
    client = TestClient(manual_app)
    feed(manual_app)
    client.post("/api/approve", json={"key": plan_key(client)}, headers=LOCAL)

    response = client.post("/api/manual/drive", json={"left": 1, "right": 1}, headers=LOCAL)

    assert response.status_code == 409
    assert "plan is running" in response.json()["detail"].lower()


def test_a_page_from_another_site_cannot_drive_the_rover(manual_app):
    client = TestClient(manual_app)

    for path, body in (
        ("/api/manual/drive", {"left": 1, "right": 1}),
        ("/api/manual/arm", {"base": 0, "shoulder": 60, "elbow": -90, "gripper": 0}),
        ("/api/manual/stop", None),
    ):
        assert client.post(path, json=body, headers=OUTSIDE).status_code == 403, path
    assert wheels(manual_app) == (0.0, 0.0)


@pytest.mark.parametrize("body", [{}, {"left": "fast", "right": 0}, {"left": 1}])
def test_a_drive_command_that_is_not_two_numbers_is_refused(manual_app, body):
    client = TestClient(manual_app)

    assert client.post("/api/manual/drive", json=body, headers=LOCAL).status_code == 422


# --- the real rover link ---------------------------------------------------------------------


class UnreachableRover:
    """A link whose rover cannot be reached, so every send is refused."""

    connected = False
    address = "ws://still-here.local:81"
    last_error = "OSError: no route"

    def __init__(self):
        self.sent = []

    def send(self, message):
        self.sent.append(message)
        return False

    def advance(self, dt):
        return []


def test_the_state_says_the_simulated_rover_is_connected(client):
    state = client.get("/api/state").json()

    assert state["rover_connected"] is True
    assert "simulated" in state["rover_address"]


def test_the_state_says_when_the_real_rover_cannot_be_reached():
    link = UnreachableRover()
    client = TestClient(server.create_app(source=None, link=link))

    state = client.get("/api/state").json()

    assert state["rover_connected"] is False
    assert state["rover_address"] == "ws://still-here.local:81"
    assert "no route" in state["rover_error"]


def test_nothing_that_moves_the_rover_is_accepted_while_it_cannot_be_reached():
    link = UnreachableRover()
    app = server.create_app(source=None, link=link)
    client = TestClient(app)
    feed(app)
    key = plan_key(client)

    for path, body in (
        ("/api/approve", {"key": key}),
        ("/api/manual/drive", {"left": 1, "right": 1}),
        ("/api/manual/arm", {"base": 0, "shoulder": 60, "elbow": -90, "gripper": 0}),
        ("/api/manual/stop", None),
    ):
        response = client.post(path, json=body, headers=LOCAL)
        assert response.status_code == 409, path
        assert "not connected" in response.json()["detail"].lower()
    assert link.sent == []
    assert client.get("/api/state").json()["phase"] == "plan_ready"  # still waiting to be approved


def test_a_whole_run_goes_through_the_real_link_to_a_rover_on_the_network():
    from rover_link import RealLink
    from sim_server import SimRoverServer
    import time as clock

    rover = SimRoverServer(WALL, speed=6.0).start()
    link = RealLink("127.0.0.1", rover.port, retry_s=0.2)
    app = server.create_app(source=None, link=link, report_writer=lambda *a: None)
    try:
        with TestClient(app) as client:
            deadline = clock.monotonic() + 5
            while clock.monotonic() < deadline and not client.get("/api/state").json()["rover_connected"]:
                clock.sleep(0.05)
            assert client.get("/api/state").json()["rover_connected"] is True

            feed(app)
            assert client.post("/api/approve", json={"key": plan_key(client)}, headers=LOCAL).status_code == 200

            deadline = clock.monotonic() + 25
            while clock.monotonic() < deadline and client.get("/api/state").json()["phase"] != "verifying":
                app.state.advance(0.05)
                clock.sleep(0.05)
            state = client.get("/api/state").json()
            assert state["phase"] == "verifying"
            assert state["progress"]["done"] == state["progress"]["total"] > 0
            assert rover.rover._stored is not None  # the plan really reached the rover over the socket
    finally:
        rover.close()


def test_choosing_the_real_rover_uses_its_name_from_the_config_and_its_own_video():
    from aruco import Config

    link, source = server.choose_rover(False, None, None, Config())

    assert (link.host, link.port) == ("still-here.local", 81)
    assert source == "http://still-here.local/stream"


def test_a_rover_given_on_the_command_line_wins_and_may_carry_a_port():
    from aruco import Config

    link, source = server.choose_rover(False, "192.168.0.50:8081", None, Config())

    assert (link.host, link.port) == ("192.168.0.50", 8081)
    assert source == "http://192.168.0.50/stream"


def test_an_explicit_camera_source_is_kept():
    from aruco import Config

    _, source = server.choose_rover(False, None, "2", Config())

    assert source == "2"


def test_simulating_uses_the_software_rover_and_a_webcam():
    from aruco import Config

    link, source = server.choose_rover(True, None, None, Config())

    assert link is None and source == "0"


@pytest.mark.parametrize("rover", [":81", "host:abc", "host:0", "host:70000"])
def test_a_bad_rover_argument_is_explained(rover):
    from aruco import Config

    with pytest.raises(ValueError, match="--rover"):
        server.choose_rover(False, rover, None, Config())


def test_the_servers_own_api_documentation_pages_are_not_published():
    client = TestClient(server.create_app(source=None))

    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404, path


# --- running over Wi-Fi: an access token for anything that is not this laptop ------------------

TOKEN = "s3cret-token"


def token_app(written=None):
    return server.create_app(source=None, access_token=TOKEN, report_writer=written or (lambda *a: None))


def test_without_a_token_configured_everyone_is_let_in_as_before(client):
    assert client.get("/api/state").status_code == 200


def test_another_device_without_the_token_is_refused_everywhere_that_matters():
    client = TestClient(token_app())

    assert client.get("/api/state").status_code == 401
    assert client.get("/api/report").status_code == 401
    assert client.get("/video").status_code == 401
    assert client.post("/api/manual/drive", json={"left": 1, "right": 1}, headers=LOCAL).status_code == 401
    assert client.post("/api/abort", headers=LOCAL).status_code == 401
    assert "access link" in client.get("/api/state").json()["detail"]


def test_a_wrong_token_is_refused():
    client = TestClient(token_app())

    assert client.get("/api/state", headers={"x-still-here-token": "nope"}).status_code == 401
    client.cookies.set("still_here_token", "nope")
    assert client.get("/api/state").status_code == 401


def test_the_right_token_in_a_header_or_a_cookie_is_let_in():
    client = TestClient(token_app())

    assert client.get("/api/state", headers={"x-still-here-token": TOKEN}).status_code == 200
    client.cookies.set("still_here_token", TOKEN)
    assert client.get("/api/state").status_code == 200


def test_opening_the_access_link_remembers_the_token_and_shows_a_clean_address():
    client = TestClient(token_app())

    first = client.get(f"/autonomous.html?token={TOKEN}", follow_redirects=False)

    assert first.status_code in (302, 307)
    assert first.headers["location"] == "/autonomous.html"
    cookie = first.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert client.get("/api/state").status_code == 200  # the cookie was kept


def test_the_front_door_with_the_token_goes_to_the_autonomous_page_signed_in():
    client = TestClient(token_app())

    response = client.get(f"/?token={TOKEN}", follow_redirects=False)

    assert response.headers["location"] == "/autonomous.html"
    assert "still_here_token" in response.headers["set-cookie"]


def test_a_wrong_token_in_the_link_gets_no_cookie():
    client = TestClient(token_app())

    response = client.get("/autonomous.html?token=wrong", follow_redirects=False)

    assert "set-cookie" not in response.headers
    assert client.get("/api/state").status_code == 401


def test_the_pages_themselves_are_open_so_a_phone_can_load_them_and_explain():
    client = TestClient(token_app())

    assert client.get("/autonomous.html").status_code == 200
    assert client.get("/operator.js").status_code == 200


def test_this_laptop_never_needs_the_token():
    client = TestClient(token_app(), client=("127.0.0.1", 50000))

    assert client.get("/api/state").status_code == 200
    assert client.post("/api/manual/stop", headers=LOCAL).status_code == 200


def test_a_page_from_another_website_is_still_refused_even_with_the_token():
    client = TestClient(token_app())

    response = client.get("/api/state", headers={"x-still-here-token": TOKEN, "origin": "https://evil.example"})

    assert response.status_code == 403


def test_the_token_is_only_made_when_the_server_is_open_to_the_network():
    assert server.access_token_for("127.0.0.1", None) is None
    assert server.access_token_for("localhost", None) is None
    open_token = server.access_token_for("0.0.0.0", None)
    assert open_token and len(open_token) >= 10
    assert server.access_token_for("0.0.0.0", None) != open_token  # a new one each time
    assert server.access_token_for("0.0.0.0", "mine") == "mine"
    assert server.access_token_for("127.0.0.1", "mine") == "mine"


def test_the_laptops_address_on_the_network_is_found_or_falls_back_to_this_machine():
    class Probe:
        def __init__(self, address):
            self.address = address

        def connect(self, target):
            if self.address is None:
                raise OSError("no network")

        def getsockname(self):
            return (self.address, 12345)

        def close(self):
            pass

    assert server.lan_address(lambda: Probe("192.168.0.20")) == "192.168.0.20"
    assert server.lan_address(lambda: Probe(None)) == "127.0.0.1"


# --- learning from past runs ----------------------------------------------------------


def test_a_clean_finished_run_is_remembered_and_adds_no_room(written):
    from experience import Experience

    experience = Experience()
    app = server.create_app(source=None, report_writer=written, experience=experience)
    client = TestClient(app)
    feed(app)
    client.post("/api/approve", json={"key": plan_key(client)}, headers=LOCAL)
    run_the_plan(app, client, "verifying")
    for _ in range(3):
        feed(app, seen([]))
    app.state.advance(0.05)
    app.state.advance(0.05)

    assert [run.trouble for run in experience.runs] == [False]
    assert client.get("/api/state").json()["learned"] is None


def test_trouble_in_past_runs_widens_the_corridor_and_the_page_says_so(written):
    from experience import Experience

    experience = Experience(step_mm=10)
    experience.record({"run_id": "old", "status": "completed", "verified": True, "obstacles_detected": 1})
    app = server.create_app(source=None, report_writer=written, experience=experience)
    client = TestClient(app)

    assert app.state.pipeline.extra_clearance_mm == 10.0
    assert "10 mm" in client.get("/api/state").json()["learned"]


def test_a_run_the_operator_stopped_teaches_nothing(written):
    from experience import Experience

    experience = Experience()
    app = server.create_app(source=None, report_writer=written, experience=experience)
    client = TestClient(app)
    feed(app)
    client.post("/api/approve", json={"key": plan_key(client)}, headers=LOCAL)
    client.post("/api/abort", headers=LOCAL)
    app.state.advance(0.05)

    assert experience.runs == ()
