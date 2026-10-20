"""The report: facts first, and a summary only when the facts back it up."""

import json

import pytest

import report
from report import (
    SafePathReport,
    build_report,
    check_summary,
    choose_summary,
    render_report,
    write_report,
)

FACTS = {
    "run_id": "stillhere-run-1",
    "status": "completed",
    "verified": True,
    "steps_completed": 4,
    "steps_planned": 4,
    "obstacles_detected": 1,
    "safe_stop_triggered": False,
}


def facts(**changes):
    return {**FACTS, **changes}


@pytest.fixture
def chimes(monkeypatch):
    heard = []
    monkeypatch.setattr(report, "play_completion_chime", lambda: heard.append(1))
    return heard


def test_good_facts_become_a_report():
    built = build_report(FACTS)

    assert isinstance(built, SafePathReport)
    assert built.steps_completed == 4 and built.verified is True


def test_a_missing_fact_is_named():
    incomplete = {k: v for k, v in FACTS.items() if k != "verified"}

    with pytest.raises(ValueError, match="verified"):
        build_report(incomplete)


@pytest.mark.parametrize(
    "bad",
    [
        {"verified": "yes"},
        {"safe_stop_triggered": 1},
        {"steps_completed": -1},
        {"steps_planned": 2.5},
        {"obstacles_detected": True},
        {"steps_completed": 5},
        {"run_id": "  "},
        {"status": ""},
    ],
)
def test_facts_that_do_not_make_sense_are_refused(bad):
    with pytest.raises(ValueError):
        build_report(facts(**bad))


def test_a_summary_that_matches_the_facts_is_allowed():
    assert check_summary(build_report(FACTS), "Run completed and verified.")


def test_a_summary_that_contradicts_the_facts_is_refused():
    unverified = build_report(facts(verified=False, status="unverified"))

    assert not check_summary(unverified, "Run completed and verified.")
    assert check_summary(unverified, "Run was not verified.")


def test_a_run_that_did_not_finish_every_step_is_not_called_completed():
    partial = build_report(facts(steps_completed=3))

    assert not check_summary(partial, "Run completed and verified.")


def test_a_made_up_summary_is_refused():
    assert not check_summary(build_report(FACTS), "Everything went wonderfully.")


def test_the_summary_is_chosen_from_the_facts():
    assert choose_summary(build_report(FACTS)) == "Run completed and verified."
    stopped = build_report(facts(safe_stop_triggered=True, verified=False))
    assert choose_summary(stopped) == "Run stopped for safety."
    assert choose_summary(build_report(facts(verified=False))) == "Run was not verified."


def test_a_verified_run_that_hit_a_safe_stop_is_not_called_completed():
    stopped = build_report(facts(safe_stop_triggered=True))

    assert choose_summary(stopped) == "Run stopped for safety."


def test_the_text_report_lists_the_facts_before_the_summary():
    text = render_report(build_report(FACTS), "Run completed and verified.")

    lines = text.splitlines()
    assert lines[0] == "STILL HERE - SAFE-PATH REPORT"
    assert "Verified: True" in lines
    assert lines.index("Verified: True") < lines.index("Summary: Run completed and verified.")


def test_an_unsupported_summary_is_left_out_and_says_so():
    text = render_report(build_report(facts(verified=False)), "Run completed and verified.")

    assert "Summary omitted" in text


def test_writing_a_report_saves_json_prints_it_and_chimes_once(tmp_path, capsys, chimes):
    path = tmp_path / "out.json"

    write_report(FACTS, str(path), "Run completed and verified.")

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["steps_completed"] == 4
    assert saved["summary"] == "Run completed and verified."
    assert "STILL HERE - SAFE-PATH REPORT" in capsys.readouterr().out
    assert len(chimes) == 1


def test_a_rejected_summary_is_not_saved(tmp_path, capsys, chimes):
    path = tmp_path / "out.json"

    write_report(facts(verified=False), str(path), "Run completed and verified.")

    assert json.loads(path.read_text(encoding="utf-8")).get("summary") is None
    assert "rejected" in capsys.readouterr().out


def test_bad_facts_write_nothing_and_do_not_chime(tmp_path, chimes):
    path = tmp_path / "out.json"

    with pytest.raises(ValueError):
        write_report(facts(steps_completed=9), str(path))

    assert not path.exists()
    assert chimes == []


def test_the_chime_falls_back_quietly_when_the_system_has_no_sound(monkeypatch, capsys):
    monkeypatch.setitem(__import__("sys").modules, "winsound", None)

    report.play_completion_chime()

    assert "chime unavailable" in capsys.readouterr().out
