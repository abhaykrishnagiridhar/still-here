// Tests for rover_json.h on the PC. No Arduino needed:
//   g++ -std=c++11 -Wall -Wextra -Wpedantic test_rover_json.cpp -o test_rover_json && ./test_rover_json
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>

#include "rover_json.h"

static int failures = 0;

#define CHECK(cond)                                                            \
    do {                                                                       \
        if (!(cond)) {                                                         \
            std::fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #cond);       \
            ++failures;                                                        \
        }                                                                      \
    } while (0)

static bool near(double a, double b) { return std::fabs(a - b) < 1e-4; }

static Command parse(const std::string& text, ParseStatus* status = nullptr) {
    Command command;
    ParseStatus result = parseCommand(text.c_str(), text.size(), &command);
    if (status) *status = result;
    return command;
}

static void a_ping_is_read() {
    ParseStatus status;
    Command c = parse("{\"type\":\"ping\",\"t\":12.5}", &status);
    CHECK(status == PARSE_OK);
    CHECK(c.type == CMD_PING);
    CHECK(c.hasT && near(c.t, 12.5));
}

static void whitespace_and_key_order_do_not_matter() {
    Command c = parse("  {\n \"left\" : 0.5 , \"type\" : \"drive\" ,\t\"right\":-0.25 }  \n");
    CHECK(c.type == CMD_DRIVE);
    CHECK(near(c.left, 0.5) && near(c.right, -0.25));
}

static void a_drive_with_missing_speeds_means_stop() {
    Command c = parse("{\"type\":\"drive\"}");
    CHECK(c.type == CMD_DRIVE);
    CHECK(c.left == 0.0f && c.right == 0.0f);
}

static void a_drive_with_a_text_speed_is_unreadable() {
    ParseStatus status;
    parse("{\"type\":\"drive\",\"left\":\"fast\",\"right\":0}", &status);
    CHECK(status == PARSE_BAD_FIELD);
}

static void an_arm_pose_keeps_the_joints_it_does_not_mention() {
    Command c = parse("{\"type\":\"arm_pose\",\"base\":10,\"elbow\":-45.5,\"speed\":0.5}");
    CHECK(c.type == CMD_ARM_POSE);
    CHECK(c.hasJoint[JOINT_BASE] && near(c.joint[JOINT_BASE], 10));
    CHECK(!c.hasJoint[JOINT_SHOULDER]);
    CHECK(c.hasJoint[JOINT_ELBOW] && near(c.joint[JOINT_ELBOW], -45.5));
    CHECK(!c.hasJoint[JOINT_GRIPPER]);
    CHECK(c.hasSpeed && near(c.speed, 0.5));
}

static void a_mode_is_manual_or_auto_only() {
    Command manual = parse("{\"type\":\"mode\",\"mode\":\"manual\"}");
    Command automatic = parse("{\"type\":\"mode\",\"mode\":\"auto\"}");
    Command other = parse("{\"type\":\"mode\",\"mode\":\"turbo\"}");
    CHECK(manual.modeValid && !manual.modeAuto);
    CHECK(automatic.modeValid && automatic.modeAuto);
    CHECK(!other.modeValid);
}

static void a_plan_with_steps_is_read() {
    Command c = parse(
        "{\"type\":\"plan\",\"plan_id\":7,\"steps\":["
        "{\"id\":1,\"action\":\"pick\",\"x\":150,\"y\":0,\"z\":20},"
        "{\"id\":2,\"action\":\"drop\",\"x\":100.5,\"y\":-90,\"z\":20}]}");
    CHECK(c.type == CMD_PLAN);
    CHECK(c.planIdValid && c.planId == 7);
    CHECK(c.stepCount == 2 && c.stepsValid);
    CHECK(c.steps[0].id == 1 && c.steps[0].pick && near(c.steps[0].x, 150));
    CHECK(c.steps[1].id == 2 && !c.steps[1].pick && near(c.steps[1].y, -90));
}

static void a_plan_step_with_an_unknown_action_is_marked_invalid() {
    Command c = parse("{\"type\":\"plan\",\"plan_id\":1,\"steps\":[{\"id\":1,\"action\":\"juggle\",\"x\":1,\"y\":2,\"z\":3}]}");
    CHECK(c.type == CMD_PLAN);
    CHECK(!c.stepsValid);
    CHECK(c.planProblem == PLAN_UNKNOWN_ACTION);
}

static void a_plan_step_missing_a_field_is_marked_invalid() {
    Command c = parse("{\"type\":\"plan\",\"plan_id\":1,\"steps\":[{\"id\":1,\"action\":\"pick\",\"x\":1,\"y\":2}]}");
    CHECK(!c.stepsValid);
    CHECK(c.planProblem == PLAN_UNREADABLE);
}

static void duplicate_step_ids_are_invalid() {
    Command c = parse("{\"type\":\"plan\",\"plan_id\":1,\"steps\":["
                      "{\"id\":1,\"action\":\"pick\",\"x\":1,\"y\":2,\"z\":3},"
                      "{\"id\":1,\"action\":\"drop\",\"x\":1,\"y\":2,\"z\":3}]}");
    CHECK(!c.stepsValid);
    CHECK(c.planProblem == PLAN_UNREADABLE);
}

static void too_many_steps_are_invalid_not_a_crash() {
    std::string text = "{\"type\":\"plan\",\"plan_id\":1,\"steps\":[";
    for (int i = 1; i <= MAX_PLAN_STEPS + 3; ++i) {
        if (i > 1) text += ",";
        text += "{\"id\":" + std::to_string(i) + ",\"action\":\"pick\",\"x\":1,\"y\":2,\"z\":3}";
    }
    text += "]}";
    Command c = parse(text);
    CHECK(c.type == CMD_PLAN);
    CHECK(!c.stepsValid);
    CHECK(c.planProblem == PLAN_TOO_MANY_STEPS);
    CHECK(c.stepCount <= MAX_PLAN_STEPS);
}

static void a_plan_with_no_steps_array_is_invalid() {
    Command c = parse("{\"type\":\"plan\",\"plan_id\":1}");
    CHECK(c.type == CMD_PLAN);
    CHECK(!c.stepsValid);
}

static void plan_ids_must_be_positive_whole_numbers() {
    CHECK(!parse("{\"type\":\"plan_start\",\"plan_id\":0}").planIdValid);
    CHECK(!parse("{\"type\":\"plan_start\",\"plan_id\":-3}").planIdValid);
    CHECK(!parse("{\"type\":\"plan_start\",\"plan_id\":2.5}").planIdValid);
    CHECK(!parse("{\"type\":\"plan_start\",\"plan_id\":\"run-001\"}").planIdValid);
    CHECK(!parse("{\"type\":\"plan_start\"}").planIdValid);
    Command ok = parse("{\"type\":\"plan_start\",\"plan_id\":935450}");
    CHECK(ok.type == CMD_PLAN_START && ok.planIdValid && ok.planId == 935450);
}

static void abort_is_read() {
    CHECK(parse("{\"type\":\"abort\"}").type == CMD_ABORT);
}

static void an_unknown_type_is_ignored_not_an_error() {
    ParseStatus status;
    Command c = parse("{\"type\":\"something_new\",\"x\":[1,2,{\"a\":null}]}", &status);
    CHECK(status == PARSE_OK);
    CHECK(c.type == CMD_UNKNOWN);
}

static void a_message_with_no_type_is_unknown() {
    ParseStatus status;
    Command c = parse("{\"left\":1}", &status);
    CHECK(status == PARSE_OK && c.type == CMD_UNKNOWN);
}

static void unknown_keys_of_any_shape_are_skipped() {
    Command c = parse("{\"extra\":{\"deep\":[1,2,[3]]},\"type\":\"ping\",\"note\":\"a \\\"quoted\\\" word\",\"flag\":true,\"nothing\":null}");
    CHECK(c.type == CMD_PING);
}

static void text_that_is_not_json_is_refused() {
    const char* bad[] = {"", "ping", "{\"type\":\"ping\"", "{\"type\":\"ping\",}", "{type:\"ping\"}",
                         "{\"type\":\"ping\"} extra", "[\"type\",\"ping\"]", "{\"type\":\"ping\",\"t\":1.}",
                         "{\"type\":\"ping\",\"t\":01}"};
    for (const char* text : bad) {
        ParseStatus status;
        parse(text, &status);
        if (status != PARSE_BAD_JSON) std::fprintf(stderr, "not refused: %s\n", text);
        CHECK(status == PARSE_BAD_JSON);
    }
}

static void numbers_json_cannot_carry_are_refused() {
    const char* bad[] = {"{\"type\":\"drive\",\"left\":NaN,\"right\":0}",
                         "{\"type\":\"drive\",\"left\":Infinity,\"right\":0}",
                         "{\"type\":\"drive\",\"left\":-Infinity,\"right\":0}"};
    for (const char* text : bad) {
        ParseStatus status;
        parse(text, &status);
        CHECK(status == PARSE_BAD_JSON);
    }
}

static void a_number_too_big_to_hold_is_a_bad_field_not_infinity() {
    ParseStatus status;
    parse("{\"type\":\"drive\",\"left\":1e999,\"right\":0}", &status);
    CHECK(status == PARSE_BAD_FIELD);
}

static void exponent_numbers_are_read() {
    Command c = parse("{\"type\":\"drive\",\"left\":5e-1,\"right\":-2.5E-1}");
    CHECK(near(c.left, 0.5) && near(c.right, -0.25));
}

static void escapes_in_strings_are_understood() {
    Command c = parse("{\"typ\\u0065\":\"pi\\u006eg\"}");
    CHECK(c.type == CMD_PING);
}

static void a_message_that_is_too_long_is_refused() {
    std::string text = "{\"type\":\"ping\",\"pad\":\"" + std::string(MAX_MESSAGE_BYTES + 10, 'a') + "\"}";
    ParseStatus status;
    parse(text, &status);
    CHECK(status == PARSE_TOO_BIG);
}

static void nesting_that_is_too_deep_is_refused_not_a_stack_overflow() {
    std::string text = "{\"type\":\"ping\",\"deep\":";
    for (int i = 0; i < 200; ++i) text += "[";
    for (int i = 0; i < 200; ++i) text += "]";
    text += "}";
    ParseStatus status;
    parse(text, &status);
    CHECK(status == PARSE_BAD_JSON);
}

static void a_long_string_value_is_skipped_safely() {
    std::string text = "{\"type\":\"ping\",\"note\":\"" + std::string(2000, 'z') + "\"}";
    ParseStatus status;
    Command c = parse(text, &status);
    CHECK(status == PARSE_OK && c.type == CMD_PING);
}

static void a_long_type_name_does_not_overflow() {
    std::string text = "{\"type\":\"" + std::string(500, 'p') + "\"}";
    ParseStatus status;
    Command c = parse(text, &status);
    CHECK(status == PARSE_OK && c.type == CMD_UNKNOWN);
}

static void a_text_with_an_embedded_null_is_refused() {
    const char raw[] = {'{', '"', 't', 'y', 'p', 'e', '"', ':', '"', 'p', 'i', 'n', 'g', '"', '}', 0, '{'};
    Command command;
    CHECK(parseCommand(raw, sizeof(raw), &command) == PARSE_BAD_JSON);
}

int main() {
    a_ping_is_read();
    whitespace_and_key_order_do_not_matter();
    a_drive_with_missing_speeds_means_stop();
    a_drive_with_a_text_speed_is_unreadable();
    an_arm_pose_keeps_the_joints_it_does_not_mention();
    a_mode_is_manual_or_auto_only();
    a_plan_with_steps_is_read();
    a_plan_step_with_an_unknown_action_is_marked_invalid();
    a_plan_step_missing_a_field_is_marked_invalid();
    duplicate_step_ids_are_invalid();
    too_many_steps_are_invalid_not_a_crash();
    a_plan_with_no_steps_array_is_invalid();
    plan_ids_must_be_positive_whole_numbers();
    abort_is_read();
    an_unknown_type_is_ignored_not_an_error();
    a_message_with_no_type_is_unknown();
    unknown_keys_of_any_shape_are_skipped();
    text_that_is_not_json_is_refused();
    numbers_json_cannot_carry_are_refused();
    a_number_too_big_to_hold_is_a_bad_field_not_infinity();
    exponent_numbers_are_read();
    escapes_in_strings_are_understood();
    a_message_that_is_too_long_is_refused();
    nesting_that_is_too_deep_is_refused_not_a_stack_overflow();
    a_long_string_value_is_skipped_safely();
    a_long_type_name_does_not_overflow();
    a_text_with_an_embedded_null_is_refused();

    if (failures == 0) {
        std::printf("all tests passed\n");
        return EXIT_SUCCESS;
    }
    std::printf("%d check(s) failed\n", failures);
    return EXIT_FAILURE;
}
