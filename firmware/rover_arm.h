#pragma once

// The arm's geometry and limits. These are the same numbers and the same maths as
// laptop/sim_rover.py (solve_pose, arm_tip) and laptop/plan_message.py (ARM_LIMITS_DEG), and
// test_rover_arm.cpp checks them against numbers produced by that Python code. If you change a
// number here, change it there too.
//
// ALL OF THESE LENGTHS ARE ASSUMPTIONS until the real arm is measured (see docs/tasks.md, D).
// Plain C++11, no Arduino headers.

#include <math.h>

#include "rover_types.h"

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

constexpr float ARM_BASE_HEIGHT_MM = 60.0f;
constexpr float ARM_LINK_1_MM = 105.0f;
constexpr float ARM_LINK_2_MM = 105.0f;
constexpr float HOVER_MM = 60.0f;  // how far above a block the gripper waits before going down

// Joint limits in degrees: base, shoulder, elbow, gripper (0 = closed, 90 = open).
constexpr float JOINT_MIN_DEG[JOINT_COUNT] = {-90.0f, 0.0f, -135.0f, 0.0f};
constexpr float JOINT_MAX_DEG[JOINT_COUNT] = {90.0f, 120.0f, 135.0f, 90.0f};

constexpr float SERVO_RATE_DPS = 120.0f;  // a joint's top speed, at arm_pose speed 1.0
constexpr float POSE_TOLERANCE_DEG = 1.0f;
constexpr float MIN_ARM_SPEED = 0.05f;
constexpr float MAX_ARM_SPEED = 1.0f;

inline Pose homePose() {
    Pose pose;
    pose.angle[JOINT_BASE] = 0.0f;
    pose.angle[JOINT_SHOULDER] = 60.0f;
    pose.angle[JOINT_ELBOW] = -90.0f;
    pose.angle[JOINT_GRIPPER] = 90.0f;
    return pose;
}

// Holds a value inside its joint's limits. NaN is not passed through: it becomes the joint's
// home angle, a safe middle value.
inline float clampJoint(int joint, float value) {
    if (value != value) return homePose().angle[joint];
    if (value < JOINT_MIN_DEG[joint]) return JOINT_MIN_DEG[joint];
    if (value > JOINT_MAX_DEG[joint]) return JOINT_MAX_DEG[joint];
    return value;
}

inline Pose clampPose(const Pose& pose) {
    Pose out;
    for (int j = 0; j < JOINT_COUNT; ++j) out.angle[j] = clampJoint(j, pose.angle[j]);
    return out;
}

// Where the gripper tip is for a pose (forward kinematics), in the arm frame, millimetres.
inline void armTip(const Pose& pose, float* x, float* y, float* z) {
    const double rad = M_PI / 180.0;
    double shoulder = pose.angle[JOINT_SHOULDER] * rad;
    double upper = shoulder + pose.angle[JOINT_ELBOW] * rad;
    double reach = ARM_LINK_1_MM * cos(shoulder) + ARM_LINK_2_MM * cos(upper);
    double height = ARM_BASE_HEIGHT_MM + ARM_LINK_1_MM * sin(shoulder) + ARM_LINK_2_MM * sin(upper);
    double base = pose.angle[JOINT_BASE] * rad;
    *x = static_cast<float>(reach * cos(base));
    *y = static_cast<float>(reach * sin(base));
    *z = static_cast<float>(height);
}

// Joint angles that put the tip at (x, y, z), elbow up (inverse kinematics). Returns false if the
// point cannot be reached or needs a joint outside its limits. On false, *out is left unchanged.
inline bool solvePose(float x, float y, float z, float gripper, Pose* out) {
    if (!isfinite(x) || !isfinite(y) || !isfinite(z) || !isfinite(gripper)) return false;
    const double deg = 180.0 / M_PI;
    double reach = hypot(static_cast<double>(x), static_cast<double>(y));
    double rise = static_cast<double>(z) - ARM_BASE_HEIGHT_MM;
    double dist = hypot(reach, rise);
    const double l1 = ARM_LINK_1_MM, l2 = ARM_LINK_2_MM;
    if (dist < 1e-6 || dist > l1 + l2 || dist < fabs(l1 - l2)) return false;
    auto clamp1 = [](double v) { return v < -1.0 ? -1.0 : (v > 1.0 ? 1.0 : v); };
    double inner = acos(clamp1((l1 * l1 + l2 * l2 - dist * dist) / (2 * l1 * l2)));
    double lift = acos(clamp1((l1 * l1 + dist * dist - l2 * l2) / (2 * l1 * dist)));
    Pose pose;
    pose.angle[JOINT_BASE] = static_cast<float>(atan2(static_cast<double>(y), static_cast<double>(x)) * deg);
    pose.angle[JOINT_SHOULDER] = static_cast<float>((atan2(rise, reach) + lift) * deg);
    pose.angle[JOINT_ELBOW] = static_cast<float>((inner - M_PI) * deg);
    pose.angle[JOINT_GRIPPER] = gripper;
    const double eps = 1e-4;
    for (int j = 0; j < JOINT_COUNT; ++j) {
        if (pose.angle[j] < JOINT_MIN_DEG[j] - eps || pose.angle[j] > JOINT_MAX_DEG[j] + eps) return false;
    }
    *out = pose;
    return true;
}

inline bool poseReached(const Pose& current, const Pose& target) {
    for (int j = 0; j < JOINT_COUNT; ++j) {
        if (fabsf(target.angle[j] - current.angle[j]) > POSE_TOLERANCE_DEG) return false;
    }
    return true;
}

// Moves every joint toward the target by at most SERVO_RATE_DPS * speed * seconds, never past it.
// This is the arm's speed limit: a servo is never told to jump.
inline Pose stepToward(const Pose& current, const Pose& target, float seconds, float speed) {
    Pose out = current;
    if (!(seconds > 0.0f)) return out;
    float step = SERVO_RATE_DPS * speed * seconds;
    for (int j = 0; j < JOINT_COUNT; ++j) {
        float error = target.angle[j] - current.angle[j];
        if (error > step) error = step;
        if (error < -step) error = -step;
        out.angle[j] = current.angle[j] + error;
    }
    return out;
}
