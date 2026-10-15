"""The learner that widens the corridor after runs that bumped something, and relaxes it after clean ones."""

import json

import pytest

from experience import Experience


def facts(run_id="r1", status="completed", verified=True, obstacles=0, safe_stop=False):
    return {
        "run_id": run_id,
        "status": status,
        "verified": verified,
        "steps_completed": 2,
        "steps_planned": 2,
        "obstacles_detected": obstacles,
        "safe_stop_triggered": safe_stop,
    }


def test_it_starts_with_no_extra_room():
    assert Experience().extra_clearance_mm == 0.0
    assert Experience().explanation is None


def test_a_clean_run_adds_no_room():
    exp = Experience()
    exp.record(facts())
    assert exp.extra_clearance_mm == 0.0


def test_one_obstacle_stop_per_block_is_normal_and_teaches_nothing():
    exp = Experience(step_mm=10)
    exp.record(facts(obstacles=1))  # 2 steps planned = 1 pick, so 1 stop is expected
    assert exp.runs[0].trouble is False


def test_a_run_where_the_rover_hit_something_adds_one_step():
    exp = Experience(step_mm=10)
    exp.record(facts(obstacles=2))
    assert exp.extra_clearance_mm == 10.0


def test_a_run_that_knocked_a_neighbouring_block_counts_too():
    exp = Experience(step_mm=10)
    exp.record(facts(status="aborted", verified=False, safe_stop=True), disturbed=True)
    assert exp.extra_clearance_mm == 10.0


def test_room_is_capped():
    exp = Experience(step_mm=10, max_extra_mm=30)
    for n in range(8):
        exp.record(facts(run_id=f"r{n}", obstacles=2))
    assert exp.extra_clearance_mm == 30.0


def test_clean_runs_push_old_trouble_out_of_the_window():
    exp = Experience(window=4, step_mm=10)
    exp.record(facts("r0", obstacles=2))
    for n in range(1, 5):
        exp.record(facts(f"r{n}"))
    assert exp.extra_clearance_mm == 0.0


def test_it_never_goes_below_zero_extra_room():
    exp = Experience()
    for n in range(20):
        exp.record(facts(f"r{n}"))
    assert exp.extra_clearance_mm == 0.0


def test_a_run_stopped_by_the_operator_is_no_evidence_either_way():
    exp = Experience(window=2, step_mm=10)
    exp.record(facts("r0", obstacles=2))
    exp.record(facts("r1", status="aborted", verified=False, safe_stop=True))
    exp.record(facts("r2", status="aborted", verified=False, safe_stop=True))
    assert exp.extra_clearance_mm == 10.0
    assert len(exp.runs) == 1


def test_an_unverified_run_with_no_bump_is_no_evidence():
    exp = Experience()
    exp.record(facts(status="unverified", verified=False))
    assert exp.runs == ()


def test_a_run_still_in_progress_is_ignored():
    exp = Experience()
    exp.record(facts(status="running", verified=False))
    assert exp.runs == ()


def test_the_same_run_is_not_counted_twice():
    exp = Experience(step_mm=10)
    exp.record(facts("r1", obstacles=2))
    exp.record(facts("r1", obstacles=2))
    assert exp.extra_clearance_mm == 10.0


def test_the_explanation_says_what_changed_and_why():
    exp = Experience(window=10, step_mm=10)
    exp.record(facts("r0", obstacles=3))
    exp.record(facts("r1"))
    text = exp.explanation
    assert "10 mm" in text and "1 of the last 2" in text


def test_what_it_learned_survives_a_restart(tmp_path):
    path = tmp_path / "experience.json"
    Experience(path=path, step_mm=10).record(facts("r0", obstacles=2))
    again = Experience(path=path, step_mm=10)
    assert again.extra_clearance_mm == 10.0
    assert [run.run_id for run in again.runs] == ["r0"]


def test_a_damaged_file_starts_empty_instead_of_crashing(tmp_path):
    path = tmp_path / "experience.json"
    path.write_text("{not json", encoding="utf-8")
    exp = Experience(path=path)
    assert exp.extra_clearance_mm == 0.0
    exp.record(facts(obstacles=2))
    assert json.loads(path.read_text(encoding="utf-8"))["runs"][0]["trouble"] is True


def test_a_file_with_nonsense_entries_keeps_only_the_good_ones(tmp_path):
    path = tmp_path / "experience.json"
    good = {"run_id": "r0", "trouble": True, "why": "the rover hit something"}
    path.write_text(json.dumps({"runs": [good, 5, {"run_id": 3}]}), encoding="utf-8")
    assert [run.run_id for run in Experience(path=path).runs] == ["r0"]


def test_settings_that_make_no_sense_are_refused():
    with pytest.raises(ValueError):
        Experience(window=0)
    with pytest.raises(ValueError):
        Experience(step_mm=-1)
    with pytest.raises(ValueError):
        Experience(max_extra_mm=-1)


def test_the_explanation_reads_naturally_for_a_single_run():
    exp = Experience(step_mm=10)
    exp.record(facts("r0", obstacles=2))
    assert exp.explanation == "Corridor widened by 10 mm each side: the last run had trouble."
