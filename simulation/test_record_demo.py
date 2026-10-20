"""The demo recorder's pure parts: captions, pulling pictures out of a video stream, and laying out a frame."""

import cv2
import numpy as np

from record_demo import (
    HEIGHT,
    WIDTH,
    caption_for,
    compose,
    extract_jpeg,
    learning_lines,
    plan_lines,
    title_card,
)


def jpeg_bytes(value=120, size=(40, 60)):
    ok, data = cv2.imencode(".jpg", np.full((size[0], size[1], 3), value, dtype=np.uint8))
    assert ok
    return data.tobytes()


def state(phase="scanning", done=0, total=0, notice=None, plan=None, message=""):
    return {
        "phase": phase,
        "message": message,
        "progress": {"done": done, "total": total},
        "notice": notice,
        "plan": plan,
        "rover_connected": True,
    }


PLAN = {
    "order": [{"n": 1, "id": 2, "x": 153.0, "y": 77.0}, {"n": 2, "id": 3, "x": 153.0, "y": 26.0}],
    "left": [{"id": 1, "reason": "not in the way"}],
}


# ---- captions -----------------------------------------------------------------------------


def test_each_phase_has_a_plain_caption_naming_the_step_of_the_loop():
    assert caption_for(state("scanning"))[0].startswith("1. SEE")
    assert caption_for(state("plan_ready", plan=PLAN))[0].startswith("2. PLAN")
    assert caption_for(state("running", 3, 8))[0].startswith("3. RUN")
    assert caption_for(state("verifying", 8, 8))[0].startswith("4. CHECK")
    assert caption_for(state("done", 8, 8))[0].startswith("5. DONE")


def test_the_run_caption_says_how_far_it_has_got():
    heading, detail = caption_for(state("running", 3, 8))

    assert "3 of 8" in detail


def test_a_replan_is_called_out_with_its_reason():
    heading, detail = caption_for(state("plan_ready", plan=PLAN, notice="the scene changed: block_2 moved"))

    assert heading.startswith("RE-PLAN") and "block_2 moved" in detail


def test_the_plan_caption_says_a_human_must_approve():
    _, detail = caption_for(state("plan_ready", plan=PLAN))

    assert "approve" in detail.lower()


def test_an_unknown_phase_still_gets_a_caption():
    assert caption_for(state("something_new"))[0]


# ---- the plan as lines of text ------------------------------------------------------------


def test_the_plan_is_listed_in_order_with_what_stays_and_why():
    lines = plan_lines(PLAN)

    assert lines[0].startswith("Remove 1: block_2")
    assert lines[1].startswith("Remove 2: block_3")
    assert lines[-1] == "Leave block_1: not in the way"


def test_no_plan_gives_no_lines():
    assert plan_lines(None) == []


# ---- pictures in a video stream -----------------------------------------------------------


def test_one_jpeg_is_pulled_out_of_a_buffer_with_the_rest_kept():
    a, b = jpeg_bytes(10), jpeg_bytes(200)
    buffer = b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + a + b"\r\n--frame\r\n" + b[:20]

    picture, rest = extract_jpeg(buffer)

    assert picture == a
    assert rest.endswith(b[:20])


def test_an_unfinished_jpeg_is_not_returned():
    picture, rest = extract_jpeg(b"junk" + jpeg_bytes()[:30])

    assert picture is None


def test_two_jpegs_come_out_one_at_a_time():
    a, b = jpeg_bytes(10), jpeg_bytes(200)
    first, rest = extract_jpeg(a + b)
    second, rest = extract_jpeg(rest)

    assert (first, second) == (a, b)


# ---- laying out a frame -------------------------------------------------------------------


def test_a_composed_frame_has_the_fixed_video_size():
    left = np.full((480, 640, 3), 50, dtype=np.uint8)
    right = np.full((296, 400, 3), 90, dtype=np.uint8)  # pictures of other sizes are fitted

    frame = compose(left, right, state("running", 2, 8, plan=PLAN))

    assert frame.shape == (HEIGHT, WIDTH, 3)


def test_missing_pictures_still_compose():
    frame = compose(None, None, state("scanning"))

    assert frame.shape == (HEIGHT, WIDTH, 3)


def test_the_frame_changes_when_the_phase_changes():
    a = compose(None, None, state("scanning"))
    b = compose(None, None, state("done", 8, 8))

    assert (a != b).any()


def test_a_title_card_is_the_video_size_and_not_blank():
    card = title_card("A title", ["one line", "another line"])

    assert card.shape == (HEIGHT, WIDTH, 3)
    assert card.std() > 5


def test_a_title_card_can_show_a_second_column():
    one = title_card("A title", ["left one", "left two"])
    two = title_card("A title", ["left one", "left two"], ["right one", "right two"])

    assert two.shape == one.shape
    assert (two[:, WIDTH // 2 :] != one[:, WIDTH // 2 :]).any()


def test_a_report_is_split_into_the_facts_and_what_happened_to_each_block():
    from record_demo import split_report

    text = (
        "STILL HERE - SAFE-PATH REPORT\nRun ID: x\nStatus: completed\nVerified: True\nSteps completed: 8\n"
        "Steps planned: 8\nObstacles detected: 1\nSafe stop triggered: False\n\nSummary: Run completed and verified.\n\n"
        "Clear after removing 4 block(s).\nSurvivor at (307, 1) mm from the rover.\n"
        "block_2 at (153, 77) mm: moved out of the way\nblock_1: left in place, not in the way\n"
    )

    facts, outcomes = split_report(text.splitlines())

    assert facts[0] == "Run ID: x" and facts[-1].startswith("Summary:")
    assert outcomes[0] == "Clear after removing 4 block(s)."
    assert "block_1: left in place, not in the way" in outcomes
    assert all("STILL HERE" not in line for line in facts + outcomes)


def test_a_fresh_plan_after_a_safety_stop_is_approved_again_but_only_once_per_stop():
    from record_demo import Approver

    approver = Approver(approve_after_s=2.0)
    plan_state = state("plan_ready", plan=PLAN)
    stopped = state("plan_ready", plan=PLAN, notice="the scene changed: a new block appeared")

    assert approver.update(plan_state, now=0.0) is False  # the plan was just shown
    assert approver.update(plan_state, now=2.5) is True  # the human approves
    assert approver.update(state("running", 1, 8), now=3.0) is False
    assert approver.update(stopped, now=4.0) is False  # a fresh plan after a stop: shown first
    assert approver.update(stopped, now=6.5) is True  # approved again
    assert approver.update(stopped, now=7.0) is False  # the same stop is not approved twice


def test_the_approver_leaves_a_plan_alone_that_has_no_key():
    from record_demo import Approver

    approver = Approver(approve_after_s=0.0)

    assert approver.update(state("scanning"), now=1.0) is False


def test_a_brief_flicker_back_to_looking_for_the_survivor_does_not_restart_the_countdown():
    from record_demo import Approver

    approver = Approver(approve_after_s=3.0)
    plan_state = state("plan_ready", plan=PLAN)

    approver.update(plan_state, now=0.0)
    approver.update(state("need_survivor"), now=1.0)  # the light was lost for a moment
    approver.update(state("scanning"), now=1.5)

    assert approver.update(plan_state, now=3.2) is True


# ---- autonomous mode: the learning shown in the video ----------------------------------------


AUTO = {
    "active": True,
    "episode": 2,
    "episodes": 3,
    "message": "Autonomous mode: run 2 of 3 approved and running.",
    "corridor_mm": 260.0,
    "extra_mm": 10.0,
    "history": [
        {"number": 1, "moved": 4, "outcome": "bumped", "brushed": "block_5", "corridor_mm": 240.0, "next_corridor_mm": 260.0},
    ],
}


def test_each_finished_run_is_one_line_with_what_was_learned():
    lines = learning_lines(AUTO)

    assert lines == ["Run 1: moved 4 blocks. Brushed block_5, so the corridor grows to 260 mm."]


def test_a_clean_run_is_one_line_too():
    clean = {**AUTO, "history": [*AUTO["history"], {"number": 2, "moved": 5, "outcome": "clean", "brushed": None,
                                                       "corridor_mm": 260.0, "next_corridor_mm": 260.0}]}

    assert learning_lines(clean)[1] == "Run 2: moved 5 blocks. Clean, with a 260 mm corridor."


def test_without_autonomous_mode_there_are_no_learning_lines():
    assert learning_lines(None) == []


def test_in_autonomous_mode_the_plan_caption_says_the_laptop_approves_it_itself():
    heading, detail = caption_for({**state("plan_ready"), "autopilot": AUTO})

    assert "approve" in detail.lower()
    assert "human" not in detail.lower()
    assert heading.startswith("2. PLAN")


def test_a_frame_with_autonomous_mode_is_still_the_fixed_size():
    frame = compose(None, None, {**state("running", 1, 8), "autopilot": AUTO})

    assert frame.shape == (HEIGHT, WIDTH, 3)
