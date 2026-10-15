"""The two-block stack test log: 10 runs, and at least 8 must pass."""

import csv

import pytest

import trial_log
from trial_log import angle_difference, format_summary, log_trial, main, read_trials, summary

GOOD = dict(
    top_found=True, bottom_found=True, top_removed=True,
    before_xy=(100.0, 50.0), after_xy=(102.0, 51.0), before_deg=90.0, after_deg=95.0,
)


def rows(path):
    with open(path, newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def test_the_columns_are_the_ones_in_the_project_log():
    with open(trial_log.TRIALS_FILE, encoding="utf-8") as file:
        header = file.readline().strip()

    assert header == ",".join(trial_log.FIELDS)


def test_a_good_trial_passes_and_is_written_with_a_header(tmp_path):
    path = tmp_path / "trials.csv"

    result = log_trial(path, **GOOD, today="2026-10-15")

    assert result["pass"] == "yes" and result["failure_cause"] == ""
    saved = rows(path)
    assert saved[0]["trial"] == "1" and saved[0]["date"] == "2026-10-15"
    assert saved[0]["bottom_shift_mm"] == "2.2"
    assert saved[0]["bottom_rotation_deg"] == "5.0"
    assert saved[0]["top_removed"] == "yes"


def test_trials_are_numbered_in_order_and_the_header_is_written_once(tmp_path):
    path = tmp_path / "trials.csv"

    for _ in range(3):
        log_trial(path, **GOOD)

    assert [r["trial"] for r in rows(path)] == ["1", "2", "3"]
    assert path.read_text(encoding="utf-8").count("trial,date") == 1


def test_a_bottom_block_that_moved_5_mm_or_more_fails(tmp_path):
    result = log_trial(tmp_path / "t.csv", **{**GOOD, "after_xy": (105.0, 50.0)})

    assert result["pass"] == "no"
    assert "moved 5.0 mm" in result["failure_cause"]


def test_a_bottom_block_that_moved_just_under_5_mm_passes(tmp_path):
    result = log_trial(tmp_path / "t.csv", **{**GOOD, "after_xy": (104.9, 50.0)})

    assert result["pass"] == "yes"


def test_a_bottom_block_that_turned_10_degrees_or_more_fails(tmp_path):
    result = log_trial(tmp_path / "t.csv", **{**GOOD, "after_deg": 100.0})

    assert result["pass"] == "no"
    assert "rotated 10.0" in result["failure_cause"]


def test_the_turn_is_measured_the_short_way_round(tmp_path):
    assert angle_difference(355, 5) == 10
    assert angle_difference(5, 355) == 10
    assert angle_difference(90, 90) == 0
    assert angle_difference(0, 180) == 180
    assert log_trial(tmp_path / "t.csv", **{**GOOD, "before_deg": 358.0, "after_deg": 3.0})["pass"] == "yes"


@pytest.mark.parametrize(
    "changes, cause",
    [
        ({"top_found": False}, "top block not found"),
        ({"bottom_found": False}, "bottom block not found"),
        ({"top_removed": False}, "top block not removed"),
    ],
)
def test_a_trial_that_missed_a_step_fails_and_says_which(tmp_path, changes, cause):
    result = log_trial(tmp_path / "t.csv", **{**GOOD, **changes})

    assert result["pass"] == "no"
    assert result["failure_cause"] == cause


def test_when_the_bottom_block_cannot_be_measured_nothing_is_invented(tmp_path):
    result = log_trial(
        tmp_path / "t.csv", top_found=True, bottom_found=False, top_removed=True,
        before_xy=None, after_xy=None, before_deg=None, after_deg=None,
    )

    assert result["bottom_shift_mm"] == "" and result["bottom_rotation_deg"] == ""
    assert result["pass"] == "no"


def test_a_removed_top_block_with_no_measurement_of_the_bottom_cannot_pass(tmp_path):
    result = log_trial(
        tmp_path / "t.csv", top_found=True, bottom_found=True, top_removed=True,
        before_xy=None, after_xy=None, before_deg=None, after_deg=None,
    )

    assert result["pass"] == "no"
    assert "not measured" in result["failure_cause"]


def test_the_limits_can_be_changed(tmp_path):
    result = log_trial(tmp_path / "t.csv", **{**GOOD, "after_xy": (108.0, 50.0)}, max_shift_mm=10.0)

    assert result["pass"] == "yes"


def test_notes_are_kept(tmp_path):
    log_trial(tmp_path / "t.csv", **GOOD, notes="gripper pads replaced")

    assert rows(tmp_path / "t.csv")[0]["notes"] == "gripper pads replaced"


def test_a_note_with_commas_and_quotes_stays_in_its_own_column(tmp_path):
    log_trial(tmp_path / "t.csv", **GOOD, notes='slow, "slipped" once')

    assert rows(tmp_path / "t.csv")[0]["notes"] == 'slow, "slipped" once'


# --- the gate: 8 of 10 -------------------------------------------------------------------


def fill(path, passes, fails):
    for _ in range(passes):
        log_trial(path, **GOOD)
    for _ in range(fails):
        log_trial(path, **{**GOOD, "top_removed": False})


def test_before_any_trial_the_gate_is_not_met(tmp_path):
    expected = {"trials": 0, "passes": 0, "counted": 0, "needed": 8, "of": 10, "met": False}

    assert summary(tmp_path / "none.csv") == expected


def test_8_passes_in_10_trials_meets_the_gate(tmp_path):
    fill(tmp_path / "t.csv", 8, 2)

    result = summary(tmp_path / "t.csv")

    assert result["passes"] == 8 and result["counted"] == 10 and result["met"] is True


def test_7_passes_in_10_trials_does_not(tmp_path):
    fill(tmp_path / "t.csv", 7, 3)

    assert summary(tmp_path / "t.csv")["met"] is False


def test_8_passes_in_fewer_than_10_trials_is_not_yet_the_gate(tmp_path):
    fill(tmp_path / "t.csv", 8, 0)

    result = summary(tmp_path / "t.csv")

    assert result["counted"] == 8 and result["met"] is False


def test_only_the_latest_10_trials_count_after_a_fix(tmp_path):
    fill(tmp_path / "t.csv", 0, 5)  # early trials, before the grip was fixed
    fill(tmp_path / "t.csv", 10, 0)

    result = summary(tmp_path / "t.csv")

    assert result["trials"] == 15 and result["counted"] == 10
    assert result["passes"] == 10 and result["met"] is True


def test_the_summary_says_what_to_do_when_the_gate_is_missed(tmp_path):
    fill(tmp_path / "t.csv", 6, 4)

    text = format_summary(summary(tmp_path / "t.csv"))

    assert "6 of the last 10" in text and "not met" in text.lower()
    assert "grip padding" in text


def test_reading_a_missing_log_gives_no_trials(tmp_path):
    assert read_trials(tmp_path / "none.csv") == []


# --- the command line --------------------------------------------------------------------


def test_the_command_adds_a_trial_and_prints_the_result(tmp_path, capsys):
    path = tmp_path / "t.csv"

    code = main([
        "add", "--file", str(path), "--top-found", "yes", "--bottom-found", "yes", "--top-removed", "yes",
        "--before-x", "100", "--before-y", "50", "--before-deg", "90",
        "--after-x", "103", "--after-y", "52", "--after-deg", "96",
    ])

    assert code == 0
    assert "PASS" in capsys.readouterr().out
    assert len(rows(path)) == 1


def test_the_command_shows_a_failed_trial_with_its_cause(tmp_path, capsys):
    code = main([
        "add", "--file", str(tmp_path / "t.csv"), "--top-found", "yes", "--bottom-found", "yes",
        "--top-removed", "no",
    ])

    assert code == 0
    out = capsys.readouterr().out
    assert "FAIL" in out and "top block not removed" in out


def test_the_command_summarises(tmp_path, capsys):
    path = tmp_path / "t.csv"
    fill(path, 8, 2)

    assert main(["summary", "--file", str(path)]) == 0
    assert "8 of the last 10" in capsys.readouterr().out


def test_half_a_measurement_is_refused(tmp_path, capsys):
    code = main([
        "add", "--file", str(tmp_path / "t.csv"), "--top-found", "yes", "--bottom-found", "yes",
        "--top-removed", "yes", "--before-x", "100",
    ])

    assert code == 1
    assert "all of" in capsys.readouterr().err
    assert not (tmp_path / "t.csv").exists()
