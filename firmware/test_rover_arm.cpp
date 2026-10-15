// Tests for rover_arm.h on the PC. The expected numbers were produced by laptop/sim_rover.py
// (solve_pose and arm_tip), so the firmware and the software rover agree exactly:
//   g++ -std=c++11 -Wall -Wextra -Wpedantic test_rover_arm.cpp -o test_rover_arm && ./test_rover_arm
#include <cmath>
#include <cstdio>
#include <cstdlib>

#include "rover_arm.h"

static int failures = 0;

#define CHECK(cond)                                                            \
    do {                                                                       \
        if (!(cond)) {                                                         \
            std::fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #cond);       \
            ++failures;                                                        \
        }                                                                      \
    } while (0)

static bool near(double a, double b, double tol = 0.01) { return std::fabs(a - b) <= tol; }

struct Case {
    float x, y, z, gripper;
    float base, shoulder, elbow;
};

static void solved_poses_match_the_software_rover() {
    const Case cases[] = {
        {150, 0, 80, 90, 0.0f, 51.49f, -87.7908f},
        {150, 40, 80, 90, 14.9314f, 49.1514f, -83.6206f},
        {100, -80, 80, 0, -38.6598f, 60.7635f, -103.7741f},
        {150, 0, 20, 90, 0.0f, 27.4013f, -84.6655f},
        {180, 20, 20, 0, 6.3402f, 15.5144f, -55.9379f},
        {60, 60, 100, 90, 45.0f, 88.7068f, -126.9349f},
        {210, 0, 60, 90, 0.0f, 0.0f, 0.0f},  // fully stretched out
    };
    for (const Case& c : cases) {
        Pose pose;
        bool ok = solvePose(c.x, c.y, c.z, c.gripper, &pose);
        CHECK(ok);
        if (!ok) continue;
        CHECK(near(pose.angle[JOINT_BASE], c.base));
        CHECK(near(pose.angle[JOINT_SHOULDER], c.shoulder));
        CHECK(near(pose.angle[JOINT_ELBOW], c.elbow));
        CHECK(near(pose.angle[JOINT_GRIPPER], c.gripper));
    }
}

static void points_that_cannot_be_reached_are_refused() {
    Pose pose;
    CHECK(!solvePose(500, 0, 60, 90, &pose));   // too far
    CHECK(!solvePose(0, 0, 60, 90, &pose));     // on the arm base
    CHECK(!solvePose(20, 0, 60, 90, &pose));    // so close the elbow would bend past its limit
    CHECK(!solvePose(150, 0, 400, 90, &pose));  // too high
    CHECK(!solvePose(NAN, 0, 60, 90, &pose));   // not a number
    CHECK(!solvePose(150, INFINITY, 60, 90, &pose));
}

static void a_solved_pose_puts_the_tip_where_it_was_asked() {
    Pose pose;
    CHECK(solvePose(150, 40, 80, 90, &pose));
    float x, y, z;
    armTip(pose, &x, &y, &z);
    CHECK(near(x, 150, 0.05) && near(y, 40, 0.05) && near(z, 80, 0.05));
}

static void forward_kinematics_match_the_software_rover() {
    float x, y, z;
    armTip(homePose(), &x, &y, &z);
    CHECK(near(x, 143.4327, 0.02) && near(y, 0.0, 0.02) && near(z, 98.4327, 0.02));

    Pose pose;
    pose.angle[JOINT_BASE] = 30;
    pose.angle[JOINT_SHOULDER] = 45;
    pose.angle[JOINT_ELBOW] = -60;
    pose.angle[JOINT_GRIPPER] = 0;
    armTip(pose, &x, &y, &z);
    CHECK(near(x, 152.1333, 0.02) && near(y, 87.8342, 0.02) && near(z, 107.0702, 0.02));
}

static void the_home_pose_is_the_software_rovers() {
    Pose home = homePose();
    CHECK(home.angle[JOINT_BASE] == 0 && home.angle[JOINT_SHOULDER] == 60);
    CHECK(home.angle[JOINT_ELBOW] == -90 && home.angle[JOINT_GRIPPER] == 90);
}

static void every_joint_is_held_inside_its_limits() {
    Pose wild;
    wild.angle[JOINT_BASE] = 500;
    wild.angle[JOINT_SHOULDER] = -50;
    wild.angle[JOINT_ELBOW] = 400;
    wild.angle[JOINT_GRIPPER] = 200;
    Pose held = clampPose(wild);
    CHECK(held.angle[JOINT_BASE] == 90 && held.angle[JOINT_SHOULDER] == 0);
    CHECK(held.angle[JOINT_ELBOW] == 135 && held.angle[JOINT_GRIPPER] == 90);

    Pose low;
    low.angle[JOINT_BASE] = -500;
    low.angle[JOINT_ELBOW] = -400;
    Pose heldLow = clampPose(low);
    CHECK(heldLow.angle[JOINT_BASE] == -90 && heldLow.angle[JOINT_ELBOW] == -135);
}

static void a_value_that_is_not_a_number_never_gets_through_the_limits() {
    Pose bad;
    bad.angle[JOINT_BASE] = NAN;
    bad.angle[JOINT_SHOULDER] = INFINITY;
    bad.angle[JOINT_ELBOW] = -INFINITY;
    bad.angle[JOINT_GRIPPER] = NAN;
    Pose held = clampPose(bad);
    for (int j = 0; j < JOINT_COUNT; ++j) {
        CHECK(std::isfinite(held.angle[j]));
        CHECK(held.angle[j] >= JOINT_MIN_DEG[j] && held.angle[j] <= JOINT_MAX_DEG[j]);
    }
}

static void the_arm_limits_match_plan_message_py() {
    // laptop/plan_message.py ARM_LIMITS_DEG: base +-90, shoulder 0..120, elbow +-135, gripper 0..90
    CHECK(JOINT_MIN_DEG[JOINT_BASE] == -90 && JOINT_MAX_DEG[JOINT_BASE] == 90);
    CHECK(JOINT_MIN_DEG[JOINT_SHOULDER] == 0 && JOINT_MAX_DEG[JOINT_SHOULDER] == 120);
    CHECK(JOINT_MIN_DEG[JOINT_ELBOW] == -135 && JOINT_MAX_DEG[JOINT_ELBOW] == 135);
    CHECK(JOINT_MIN_DEG[JOINT_GRIPPER] == 0 && JOINT_MAX_DEG[JOINT_GRIPPER] == 90);
}

static void a_pose_is_reached_when_every_joint_is_within_the_tolerance() {
    Pose a = homePose(), b = homePose();
    CHECK(poseReached(a, b));
    b.angle[JOINT_ELBOW] += POSE_TOLERANCE_DEG * 0.9f;
    CHECK(poseReached(a, b));
    b.angle[JOINT_ELBOW] += POSE_TOLERANCE_DEG * 0.5f;
    CHECK(!poseReached(a, b));
}

static void a_pose_moves_toward_its_target_no_faster_than_the_rate() {
    Pose from = homePose(), target = homePose();
    target.angle[JOINT_BASE] = 90;
    target.angle[JOINT_ELBOW] = -85;  // only 5 degrees to go
    Pose next = stepToward(from, target, 0.5f, 1.0f);  // 0.5 s at 120 deg/s = at most 60 degrees
    CHECK(near(next.angle[JOINT_BASE], 60.0, 1e-3));
    CHECK(near(next.angle[JOINT_ELBOW], -85.0, 1e-3));  // arrives, never overshoots
    Pose slow = stepToward(from, target, 0.5f, 0.25f);  // a quarter of the speed
    CHECK(near(slow.angle[JOINT_BASE], 15.0, 1e-3));
}

static void a_zero_or_backwards_time_step_moves_nothing() {
    Pose from = homePose(), target = homePose();
    target.angle[JOINT_BASE] = 90;
    CHECK(near(stepToward(from, target, 0.0f, 1.0f).angle[JOINT_BASE], 0.0));
    CHECK(near(stepToward(from, target, -1.0f, 1.0f).angle[JOINT_BASE], 0.0));
}

int main() {
    solved_poses_match_the_software_rover();
    points_that_cannot_be_reached_are_refused();
    a_solved_pose_puts_the_tip_where_it_was_asked();
    forward_kinematics_match_the_software_rover();
    the_home_pose_is_the_software_rovers();
    every_joint_is_held_inside_its_limits();
    a_value_that_is_not_a_number_never_gets_through_the_limits();
    the_arm_limits_match_plan_message_py();
    a_pose_is_reached_when_every_joint_is_within_the_tolerance();
    a_pose_moves_toward_its_target_no_faster_than_the_rate();
    a_zero_or_backwards_time_step_moves_nothing();

    if (failures == 0) {
        std::printf("all tests passed\n");
        return EXIT_SUCCESS;
    }
    std::printf("%d check(s) failed\n", failures);
    return EXIT_FAILURE;
}
