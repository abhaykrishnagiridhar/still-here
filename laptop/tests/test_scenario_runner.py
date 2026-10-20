"""Replaying a scenario of rover messages against the software rover or a real one."""

import json
import threading

import pytest
from websockets.sync.server import serve

import scenario_runner
from scenario_runner import RealTarget, SimTarget, load_scenario, main, run_scenario
from sim_rover import SimRover

BUNDLED = scenario_runner.DEFAULT_SCENARIO

PICK = {"id": 1, "action": "pick", "x": 150, "y": 0, "z": 20}
DROP = {"id": 2, "action": "drop", "x": 100, "y": -80, "z": 20}


def scenario(steps, blocks=((1, 150.0, 0.0),)):
    return {
        "name": "test",
        "world": {"blocks": [{"id": i, "x": x, "y": y} for i, x, y in blocks]},
        "steps": steps,
    }


def results_ok(report):
    return [r.ok for r in report.results]


# --- the bundled scenario ----------------------------------------------------------------


def test_the_bundled_scenario_passes_on_the_software_rover():
    report = run_scenario(load_scenario(BUNDLED), SimTarget(load_scenario(BUNDLED)))

    assert report.passed and all(results_ok(report))
    assert len(report.results) >= 6


def test_the_bundled_scenario_is_valid_protocol():
    from plan_message import build_plan_message

    for step in load_scenario(BUNDLED)["steps"]:
        message = step.get("send")
        if message and message["type"] == "plan":
            build_plan_message(message["plan_id"], message["steps"])


# --- how steps are judged ----------------------------------------------------------------


def test_a_message_the_rover_never_sends_fails_the_step_after_its_timeout():
    steps = [{"wait_for": {"type": "event", "code": "never_happens"}, "timeout_s": 0.5}]

    report = run_scenario(scenario(steps), SimTarget(scenario(steps)))

    assert not report.passed
    assert "never_happens" in report.results[0].detail


def test_after_a_failed_step_the_rest_are_not_run():
    steps = [
        {"wait_for": {"type": "event", "code": "never_happens"}, "timeout_s": 0.3},
        {"send": {"type": "abort"}},
    ]

    report = run_scenario(scenario(steps), SimTarget(scenario(steps)))

    assert len(report.results) == 1


def test_every_field_in_a_wait_has_to_match():
    steps = [
        {"send": {"type": "plan", "plan_id": 1, "steps": [PICK, DROP]}},
        {"wait_for": {"type": "event", "code": "plan_stored", "detail": "5 steps"}, "timeout_s": 0.5},
    ]

    report = run_scenario(scenario(steps), SimTarget(scenario(steps)))

    assert not report.passed  # the detail says 2 steps


def test_a_message_can_only_satisfy_one_wait_so_order_is_checked():
    steps = [
        {"send": {"type": "plan", "plan_id": 1, "steps": [PICK]}},
        {"wait_for": {"type": "event", "code": "plan_stored"}, "timeout_s": 1},
        {"wait_for": {"type": "event", "code": "plan_stored"}, "timeout_s": 0.3},
    ]

    report = run_scenario(scenario(steps), SimTarget(scenario(steps)))

    assert results_ok(report) == [True, True, False]


def test_a_failed_pick_is_caught_when_the_world_has_no_block_there():
    steps = [
        {"send": {"type": "plan", "plan_id": 1, "steps": [PICK]}},
        {"wait_for": {"type": "state", "plan_id": 1}, "timeout_s": 2},
        {"send": {"type": "plan_start", "plan_id": 1}},
        {"wait_for": {"type": "step_done", "step_id": 1, "ok": True}, "timeout_s": 10},
    ]

    report = run_scenario(scenario(steps, blocks=()), SimTarget(scenario(steps, blocks=())))

    assert not report.passed


def test_a_long_wait_keeps_the_link_alive_with_pings():
    steps = [{"wait_for": {"type": "event", "code": "never_happens"}, "timeout_s": 5}]
    sc = scenario(steps)

    report = run_scenario(sc, SimTarget(sc))

    assert not any(m.get("code") == "link_lost" for m in report.messages)


def test_the_report_keeps_every_message_the_rover_sent():
    steps = [
        {"send": {"type": "plan", "plan_id": 1, "steps": [PICK]}},
        {"wait_for": {"type": "event", "code": "plan_stored"}, "timeout_s": 1},
    ]
    sc = scenario(steps)

    report = run_scenario(sc, SimTarget(sc))

    assert any(m.get("code") == "plan_stored" for m in report.messages)


# --- a bad scenario file -----------------------------------------------------------------


@pytest.mark.parametrize(
    "body, message",
    [
        ("not json", "not valid JSON"),
        ("[]", "must be an object"),
        ('{"name": "x"}', "steps"),
        ('{"steps": []}', "steps"),
        ('{"steps": [{"hello": 1}]}', "send or wait_for"),
        ('{"steps": [{"send": {"plan_id": 1}}]}', "type"),
        ('{"steps": [{"wait_for": {}}]}', "wait_for"),
        ('{"steps": [{"wait_for": {"type": "state"}, "timeout_s": -1}]}', "timeout_s"),
        ('{"steps": [{"send": {"type": "ping"}, "wait_for": {"type": "state"}}]}', "only one"),
    ],
)
def test_a_broken_scenario_says_what_is_wrong(tmp_path, body, message):
    path = tmp_path / "bad.json"
    path.write_text(body, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        load_scenario(path)


def test_a_missing_scenario_file_is_named(tmp_path):
    with pytest.raises(FileNotFoundError, match="nope.json"):
        load_scenario(tmp_path / "nope.json")


# --- the software rover as a target ------------------------------------------------------


def test_the_sim_target_hands_back_what_the_rover_sends():
    target = SimTarget({"world": {"blocks": []}, "steps": []})
    target.send({"type": "plan", "plan_id": 1, "steps": [PICK]})

    messages = target.poll(0.1)

    assert any(m.get("code") == "plan_stored" for m in messages)


def test_the_sim_world_blocks_are_where_the_scenario_says():
    target = SimTarget({"world": {"blocks": [{"id": 7, "x": 120.0, "y": -30.0, "layer": 2}]}, "steps": []})

    block = target.rover.blocks[7].block

    assert (block.x, block.y, block.layer) == (120.0, -30.0, 2)


# --- a real rover as a target (here a fake one on this machine) -------------------------


class FakeRover:
    """A WebSocket server wrapping the software rover, so the real-rover code path runs."""

    def __init__(self):
        self.rover = SimRover()
        self.received = []
        self.server = serve(self.handle, "127.0.0.1", 0)
        self.port = self.server.socket.getsockname()[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def handle(self, connection):
        while True:
            try:
                raw = connection.recv(timeout=0.05)
            except TimeoutError:
                for message in self.rover.step(0.05):
                    connection.send(json.dumps(message))
                continue
            except Exception:
                return
            message = json.loads(raw)
            self.received.append(message)
            for reply in self.rover.handle(message):
                connection.send(json.dumps(reply))

    def close(self):
        self.server.shutdown()


@pytest.fixture
def fake_rover():
    rover = FakeRover()
    yield rover
    rover.close()


def test_a_real_target_sends_messages_and_hears_back(fake_rover):
    steps = [
        {"send": {"type": "plan", "plan_id": 1, "steps": [PICK]}},
        {"wait_for": {"type": "event", "code": "plan_stored"}, "timeout_s": 3},
        {"wait_for": {"type": "state", "plan_id": 1}, "timeout_s": 3},
    ]
    target = RealTarget("127.0.0.1", fake_rover.port)

    try:
        report = run_scenario(scenario(steps), target)
    finally:
        target.close()

    assert report.passed
    assert any(m["type"] == "ping" for m in fake_rover.received)  # the link is kept alive


def test_a_real_target_that_is_not_there_is_reported_not_raised():
    with pytest.raises(ConnectionError, match="127.0.0.1"):
        RealTarget("127.0.0.1", 1)


# --- the command line --------------------------------------------------------------------


def test_the_command_runs_the_bundled_scenario_on_the_software_rover(capsys):
    code = main([])

    out = capsys.readouterr().out
    assert code == 0
    assert "PASS" in out and "RESULT: all steps passed" in out


def test_the_command_fails_with_a_non_zero_code_when_a_step_fails(tmp_path, capsys):
    path = tmp_path / "s.json"
    path.write_text(json.dumps(scenario([{"wait_for": {"type": "event", "code": "never"}, "timeout_s": 0.3}])))

    code = main([str(path)])

    assert code == 1
    assert "FAIL" in capsys.readouterr().out


def test_a_real_run_needs_an_address(capsys):
    assert main(["--target", "real", "--confirm-real"]) == 2
    assert "--ip" in capsys.readouterr().err


def test_a_real_run_must_be_confirmed_because_it_can_move_the_rover(capsys):
    assert main(["--target", "real", "--ip", "127.0.0.1"]) == 2
    assert "--confirm-real" in capsys.readouterr().err


def test_a_real_run_against_a_rover_that_is_not_there_exits_cleanly(capsys):
    code = main(["--target", "real", "--ip", "127.0.0.1", "--port", "1", "--confirm-real"])

    assert code == 1
    assert "Could not connect" in capsys.readouterr().err


def test_the_command_reports_a_missing_scenario(tmp_path, capsys):
    assert main([str(tmp_path / "nope.json")]) == 1
    assert "nope.json" in capsys.readouterr().err
