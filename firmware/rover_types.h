#pragma once

// Small shared types for the rover logic. Plain C++11 with no Arduino headers, so the same code
// builds for the ESP32 and for the PC tests (see test_rover_*.cpp).

enum Joint { JOINT_BASE = 0, JOINT_SHOULDER = 1, JOINT_ELBOW = 2, JOINT_GRIPPER = 3, JOINT_COUNT = 4 };

// Joint angles in degrees, in the same frame as docs/protocol.md and laptop/sim_rover.py.
struct Pose {
    float angle[JOINT_COUNT];
    Pose() {
        for (int i = 0; i < JOINT_COUNT; ++i) angle[i] = 0.0f;
    }
};
