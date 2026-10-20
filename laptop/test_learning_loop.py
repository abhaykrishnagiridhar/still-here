"""The whole learning loop, end to end, with no Blender and no camera.

Real: the server's rover loop, the operator, the route planner, experience.py and the autopilot.
Simulated: the rover (sim_rover.py, with the buggy's real width hidden from the planner) and the picture,
which is made from where the simulated rover says each block is.

What it proves: on the first run the planner leaves the side block, the buggy brushes it, the laptop learns to
leave more room, and on the second run the planner moves that block too and nothing is touched.
"""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import server
from demo_world import BLOCKS, BUGGY_TRUE_HALF_WIDTH_MM, FIRE_MM, FRAME_MM, HEAT_RADIUS_MM, SURVIVOR_MM
from experience import Experience
from models import HeatZone
from route import DEFAULT_CORRIDOR_MM, route
from sim_rover import SimRover

DT = 0.05


class TwinLink:
    """A rover link to an in-process simulated rover, like the Blender twin but with no 3D."""

    supports_world_reset = True
    connected = True
    address = "the test twin"
    last_error = ""

    def __init__(self):
        self.rover = SimRover(BLOCKS, survivor=SURVIVOR_MM, buggy_half_width_mm=BUGGY_TRUE_HALF_WIDTH_MM)
        self.overlays = []
        self._inbox = []
        self._since_ping = 0.5

    def send(self, message):
        if message.get("type") == "overlay":
            self.overlays.append(message)
            return True
        self._inbox.extend(self.rover.handle(message))
        return True

    def advance(self, dt):
        self._since_ping += dt
        if self._since_ping >= 0.5:
            self._since_ping = 0.0
            self._inbox.extend(self.rover.handle({"type": "ping", "t": self.rover.t}))
        out, self._inbox = self._inbox + self.rover.step(dt), []
        return out


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def picture(link, extra_mm):
    """What the camera pipeline would decide from the rover's blocks, given the corridor it was told to use."""
    fx, fy, _ = FIRE_MM
    blocks = [wb.block for wb in link.rover.blocks.values()]
    corridor = DEFAULT_CORRIDOR_MM + 2 * extra_mm
    result = route(blocks, [HeatZone(fx, fy, HEAT_RADIUS_MM)], (0.0, 0.0), SURVIVOR_MM, bounds=FRAME_MM, corridor=corridor)
    return SimpleNamespace(result=result, survivor=(320, 100), px_per_mm=1.5)


@pytest.fixture
def world(tmp_path):
    clock = Clock()
    link = TwinLink()
    experience = Experience(step_mm=10.0)
    app = server.create_app(
        source=None,
        link=link,
        experience=experience,
        report_path=tmp_path / "report.json",
        report_writer=lambda *args: None,
        autopilot_episodes=2,
    )
    operator = app.state.operator
    operator._clock = clock  # the operator's and the autopilot's timers follow the test clock
    app.state.autopilot._clock = clock

    steps = [0]

    def play(seconds):
        for _ in range(round(seconds / DT)):
            clock.now += DT
            app.state.advance(DT)
            steps[0] += 1
            if steps[0] % 5 == 0:  # a camera gives a few pictures a second, not one per tick
                operator.observe(picture(link, experience.extra_clearance_mm))

    return SimpleNamespace(app=app, link=link, experience=experience, operator=operator, play=play)


def test_the_first_run_leaves_the_side_block_and_brushes_it(world):
    world.play(60)

    first = world.app.state.autopilot.summary()["history"][0]
    assert first["moved"] == 4
    assert first["outcome"] == "bumped"
    assert first["brushed"] == "block_5"


def test_the_laptop_learns_from_the_bump_and_widens_the_corridor(world):
    world.play(60)

    assert world.experience.extra_clearance_mm == 10.0
    assert world.experience.runs[0].trouble is True


def test_the_second_run_moves_the_side_block_too_and_touches_nothing(world):
    world.play(160)

    first, second = world.app.state.autopilot.summary()["history"]
    assert second["moved"] == 5
    assert second["outcome"] == "clean"
    assert second["corridor_mm"] == first["next_corridor_mm"] == DEFAULT_CORRIDOR_MM + 20.0


def test_autonomous_mode_finishes_by_itself_after_the_last_run(world):
    world.play(220)

    summary = world.app.state.autopilot.summary()
    assert summary["active"] is False
    assert len(summary["history"]) == 2
    assert "finished" in summary["message"].lower()


def test_the_twin_is_told_the_run_and_the_corridor_all_the_way_through(world):
    world.play(160)

    runs = {overlay["episode"] for overlay in world.link.overlays}
    corridors = {overlay["corridor_mm"] for overlay in world.link.overlays}
    assert runs == {1, 2}
    assert corridors == {DEFAULT_CORRIDOR_MM, DEFAULT_CORRIDOR_MM + 20.0}


def test_the_operator_page_gets_the_autopilot_summary(world):
    world.play(5)

    body = TestClient(world.app).get("/api/state").json()

    assert body["autopilot"]["episodes"] == 2
    assert body["autopilot"]["active"] is True


def test_a_person_stopping_the_run_ends_autonomous_mode_for_good(world):
    for _ in range(200):  # until the rover is really working through the plan
        world.play(0.5)
        if world.operator.state()["phase"] == "running":
            break
    assert world.operator.state()["phase"] == "running"
    world.operator.abort()

    world.play(40)

    summary = world.app.state.autopilot.summary()
    assert summary["active"] is False
    assert summary["history"] == []


def test_autonomous_mode_is_refused_with_any_link_that_cannot_reset_the_course():
    class RealLikeLink:
        connected = True

        def send(self, message):
            return True

    with pytest.raises(ValueError, match="never a real one"):
        server.create_app(source=None, link=RealLikeLink(), autopilot_episodes=2)


def test_without_autonomous_mode_the_page_state_says_so():
    body = TestClient(server.create_app(source=None)).get("/api/state").json()

    assert body["autopilot"] is None
