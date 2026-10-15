#pragma once

// The rover's behaviour, with no hardware in it. It follows docs/protocol.md (including the
// "Proposed clarifications") and does what laptop/sim_rover.py does, plus what docs/power.md asks of
// the firmware. Everything the real rover touches goes through RoverHardware, and everything it
// says goes through RoverSink, so test_rover_core.cpp can run all of it on a PC with fakes.
// Plain C++11, no Arduino headers, no heap.
//
// SAFETY RULES BUILT IN
//   - Wheels start stopped and ramp up and down over about 200 ms. They stop before reversing.
//   - A joint never moves faster than SERVO_RATE_DPS * speed. Every angle is held inside its limits.
//   - The wheels and the arm do not move at the same moment: the last command wins.
//   - abort stops the wheels at once and holds the arm where it is.
//   - No ping for 2 s: with no plan running the wheels stop and the arm holds. A running plan
//     carries on to its end, and plan_finished is reported when the link comes back.
//   - Pack voltage below 6.8 V warns, below 6.4 V stops the motors until it recovers (docs/power.md).
//   - Unreadable messages are ignored. A step the arm cannot reach is reported, never forced.

#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "rover_arm.h"
#include "rover_json.h"

constexpr uint32_t LINK_TIMEOUT_MS = 2000;
constexpr uint32_t STATE_PERIOD_MS = 200;    // 5 Hz
constexpr uint32_t SENSORS_PERIOD_MS = 500;  // 2 Hz
constexpr float WHEEL_RAMP_PER_S = 5.0f;     // full speed in 200 ms
constexpr float WHEEL_STOPPED = 0.02f;       // below this a wheel counts as stopped
constexpr uint32_t ACTION_SETTLE_MS = 300;   // let the servos physically arrive before the next move
constexpr float BATTERY_WARN_V = 6.8f;
constexpr float BATTERY_STOP_V = 6.4f;
constexpr float BATTERY_CLEAR_V = 7.0f;      // voltage must recover to this before moving again
constexpr float BATTERY_SMOOTHING = 0.2f;    // 0..1, higher follows the reading faster

struct SensorReadings {
    int obstacleLeft, obstacleRight, flameLeft, flameRight;  // 1 tripped, 0 clear, -1 not available
    float tempC, humPct;                                      // NAN when not available
    SensorReadings()
        : obstacleLeft(-1), obstacleRight(-1), flameLeft(-1), flameRight(-1), tempC(NAN), humPct(NAN) {}
};

class RoverHardware {
public:
    virtual ~RoverHardware() {}
    virtual void setWheels(float left, float right) = 0;  // -1..1, already ramped and limited
    virtual void setJoints(const Pose& pose) = 0;         // protocol degrees, already limited
    virtual SensorReadings readSensors() = 0;
    virtual float batteryVolts() = 0;  // pack volts, or NAN when it cannot be read
};

class RoverSink {
public:
    virtual ~RoverSink() {}
    virtual void send(const char* json) = 0;  // one complete JSON object
};

class RoverCore {
public:
    RoverCore(RoverHardware& hardware, RoverSink& sink)
        : hw_(hardware), sink_(sink), startMs_(0), lastTickMs_(0), pose_(homePose()), target_(homePose()),
          armSpeed_(1.0f), autoMode_(false), desiredLeft_(0), desiredRight_(0), appliedLeft_(0), appliedRight_(0),
          linkUp_(true), lastPingMs_(0), finishedOffline_(false), storedPlanId_(0), stepCount_(0), running_(false),
          stepIndex_(0), actionCount_(0), actionIndex_(0), settleStartMs_(0), currentStepId_(0), carrying_(false),
          batteryV_(NAN), batteryWarned_(false), batteryStopped_(false), nextStateMs_(0), nextSensorsMs_(0) {}

    // Call once at power-up. The wheels are stopped and the arm is told to hold its home pose.
    void begin(uint32_t nowMs) {
        startMs_ = lastTickMs_ = lastPingMs_ = nowMs;
        nextStateMs_ = nextSensorsMs_ = nowMs;
        hw_.setWheels(0.0f, 0.0f);
        hw_.setJoints(pose_);
    }

    void handle(const Command& c, uint32_t nowMs) {
        switch (c.type) {
            case CMD_PING: onPing(nowMs); break;
            case CMD_MODE:
                if (c.modeValid) autoMode_ = c.modeAuto;
                break;
            case CMD_DRIVE: onDrive(c); break;
            case CMD_ARM_POSE: onArmPose(c); break;
            case CMD_PLAN: onPlan(c); break;
            case CMD_PLAN_START: onPlanStart(c, nowMs); break;
            case CMD_ABORT: onAbort(); break;
            default: break;  // unknown messages are ignored, not errors
        }
    }

    void tick(uint32_t nowMs) {
        uint32_t elapsed = nowMs - lastTickMs_;  // wraps correctly
        lastTickMs_ = nowMs;
        if (elapsed > 100) elapsed = 100;  // a long pause must not become one huge jump
        float dt = elapsed / 1000.0f;

        checkLink(nowMs);
        checkBattery();
        if (obstacleStop_) limitForObstacles();
        if (running_) runPlan(nowMs);
        rampWheels(dt);
        if (wheelsStopped()) pose_ = stepToward(pose_, target_, dt, armSpeed_);  // the arm waits for the wheels
        hw_.setWheels(appliedLeft_, appliedRight_);
        hw_.setJoints(pose_);

        if (static_cast<int32_t>(nowMs - nextStateMs_) >= 0) {
            sendState(nowMs);
            nextStateMs_ = (nowMs - nextStateMs_ > 1000) ? nowMs + STATE_PERIOD_MS : nextStateMs_ + STATE_PERIOD_MS;
        }
        if (static_cast<int32_t>(nowMs - nextSensorsMs_) >= 0) {
            sendSensors();
            nextSensorsMs_ = (nowMs - nextSensorsMs_ > 1000) ? nowMs + SENSORS_PERIOD_MS : nextSensorsMs_ + SENSORS_PERIOD_MS;
        }
    }

    // The operator's connection closed. Make the link time out on the next tick instead of waiting
    // two more seconds: with no plan running the wheels stop and the arm holds at once. A running
    // plan is NOT stopped (docs/protocol.md: it carries on and reports when the link returns).
    void connectionClosed(uint32_t nowMs) { lastPingMs_ = nowMs - LINK_TIMEOUT_MS - 1; }

    // Stop forward driving while an IR obstacle sensor is tripped (reversing stays allowed). Leave it
    // off until the sensors' polarity has been checked on the bench: one that always reads "tripped"
    // would stop the rover ever driving forward.
    void setObstacleStop(bool on) { obstacleStop_ = on; }

    // Read-only views, for tests and for the serial status line.
    const Pose& pose() const { return pose_; }
    float wheelLeft() const { return appliedLeft_; }
    float wheelRight() const { return appliedRight_; }
    bool linkUp() const { return linkUp_; }
    bool planRunning() const { return running_; }
    long storedPlanId() const { return storedPlanId_; }
    bool carrying() const { return carrying_; }
    bool batteryStopped() const { return batteryStopped_; }
    bool autoMode() const { return autoMode_; }

private:
    struct Action {
        Pose pose;
        int carryAfter;  // -1 leave as is, 0 not carrying, 1 carrying
        Action() : carryAfter(-1) {}
    };

    // ---- sending ------------------------------------------------------------------------------
    void event(const char* code, const char* detail) {
        char buf[160];
        snprintf(buf, sizeof buf, "{\"type\":\"event\",\"code\":\"%s\",\"detail\":\"%s\"}", code, detail);
        sink_.send(buf);
    }

    static int number(char* out, size_t size, float value) {
        return isfinite(value) ? snprintf(out, size, "%.2f", value) : snprintf(out, size, "null");
    }

    void sendState(uint32_t nowMs) {
        char buf[320];
        char planId[16] = "null", stepId[16] = "null";
        if (storedPlanId_ != 0) snprintf(planId, sizeof planId, "%ld", storedPlanId_);
        if (running_) snprintf(stepId, sizeof stepId, "%ld", currentStepId_);
        const char* status = running_ ? "running" : (carrying_ ? "holding" : "idle");
        snprintf(buf, sizeof buf,
                 "{\"type\":\"state\",\"t\":%.3f,\"mode\":\"%s\",\"arm\":{\"base\":%.2f,\"shoulder\":%.2f,"
                 "\"elbow\":%.2f,\"gripper\":%.2f},\"plan_id\":%s,\"step_id\":%s,\"status\":\"%s\"}",
                 (nowMs - startMs_) / 1000.0, autoMode_ ? "auto" : "manual", pose_.angle[JOINT_BASE],
                 pose_.angle[JOINT_SHOULDER], pose_.angle[JOINT_ELBOW], pose_.angle[JOINT_GRIPPER], planId, stepId,
                 status);
        sink_.send(buf);
    }

    static const char* flag(int value) { return value < 0 ? "null" : (value ? "true" : "false"); }

    void sendSensors() {
        SensorReadings s = hw_.readSensors();
        char temp[16], hum[16], batt[16], buf[320];
        number(temp, sizeof temp, s.tempC);
        number(hum, sizeof hum, s.humPct);
        number(batt, sizeof batt, batteryV_);
        snprintf(buf, sizeof buf,
                 "{\"type\":\"sensors\",\"ir_obstacle\":{\"left\":%s,\"right\":%s},\"ir_flame\":{\"left\":%s,"
                 "\"right\":%s},\"dht\":{\"temp_c\":%s,\"hum_pct\":%s},\"battery_v\":%s}",
                 flag(s.obstacleLeft), flag(s.obstacleRight), flag(s.flameLeft), flag(s.flameRight), temp, hum, batt);
        sink_.send(buf);
    }

    void stepDone(bool ok, const char* reason) {
        char buf[200];
        snprintf(buf, sizeof buf, "{\"type\":\"step_done\",\"plan_id\":%ld,\"step_id\":%ld,\"ok\":%s,\"reason\":\"%s\"}",
                 storedPlanId_, currentStepId_, ok ? "true" : "false", reason);
        sink_.send(buf);
    }

    // ---- commands -----------------------------------------------------------------------------
    void onPing(uint32_t nowMs) {
        lastPingMs_ = nowMs;
        if (linkUp_) return;
        linkUp_ = true;
        event("link_restored", "");
        if (finishedOffline_) {
            finishedOffline_ = false;
            event("plan_finished", "finished while link was down");
        }
    }

    void onDrive(const Command& c) {
        if (running_ || batteryStopped_) return;  // a stored plan owns the rover until it ends or is aborted
        desiredLeft_ = clampWheel(c.left);
        desiredRight_ = clampWheel(c.right);
        if ((desiredLeft_ != 0.0f || desiredRight_ != 0.0f) && !poseReached(pose_, target_)) target_ = pose_;  // last command wins
    }

    void onArmPose(const Command& c) {
        if (running_ || batteryStopped_) return;
        for (int j = 0; j < JOINT_COUNT; ++j) {
            if (c.hasJoint[j]) target_.angle[j] = clampJoint(j, c.joint[j]);
        }
        float speed = c.hasSpeed && isfinite(c.speed) ? c.speed : 1.0f;
        armSpeed_ = speed < MIN_ARM_SPEED ? MIN_ARM_SPEED : (speed > MAX_ARM_SPEED ? MAX_ARM_SPEED : speed);
        desiredLeft_ = desiredRight_ = 0.0f;  // stop the wheels first, then the arm moves
    }

    void onPlan(const Command& c) {
        if (running_) return event("bad_plan", "a plan is running");
        if (!c.planIdValid || !c.stepsValid) {
            const char* why = c.planProblem == PLAN_UNKNOWN_ACTION   ? "unknown action"
                              : c.planProblem == PLAN_TOO_MANY_STEPS ? "too many steps"
                                                                     : "could not read plan";
            return event("bad_plan", why);
        }
        stepCount_ = c.stepCount;
        for (int i = 0; i < stepCount_; ++i) steps_[i] = c.steps[i];
        storedPlanId_ = c.planId;
        char detail[24];
        snprintf(detail, sizeof detail, "%d steps", stepCount_);
        event("plan_stored", detail);
    }

    void onPlanStart(const Command& c, uint32_t nowMs) {
        if (batteryStopped_) return event("bad_plan", "battery too low");
        if (running_ || !c.planIdValid || storedPlanId_ == 0 || storedPlanId_ != c.planId) {
            return event("bad_plan", "no stored plan with that id");
        }
        running_ = true;
        stepIndex_ = 0;
        hardStopWheels();
        beginStep(nowMs);
    }

    void onAbort() {
        hardStopWheels();
        target_ = pose_;  // hold where it is
        running_ = false;
        event("aborted", "");
    }

    // ---- the plan runner (mirrors sim_rover.py) ---------------------------------------------
    void beginStep(uint32_t nowMs) {
        while (running_) {
            if (stepIndex_ >= stepCount_) return finishPlan();
            const PlanStep& step = steps_[stepIndex_];
            currentStepId_ = step.id;
            float hold = step.pick ? JOINT_MAX_DEG[JOINT_GRIPPER] : JOINT_MIN_DEG[JOINT_GRIPPER];
            float end = step.pick ? JOINT_MIN_DEG[JOINT_GRIPPER] : JOINT_MAX_DEG[JOINT_GRIPPER];
            Pose hover, down;
            if (!solvePose(step.x, step.y, step.z + HOVER_MM, hold, &hover) || !solvePose(step.x, step.y, step.z, hold, &down)) {
                stepDone(false, "unreachable");
                ++stepIndex_;
                continue;
            }
            actions_[0].pose = hover;
            actions_[1].pose = down;
            actions_[2].pose = down;
            actions_[2].pose.angle[JOINT_GRIPPER] = end;
            actions_[2].carryAfter = step.pick ? 1 : 0;
            actions_[3].pose = hover;
            actions_[3].pose.angle[JOINT_GRIPPER] = end;
            actions_[0].carryAfter = actions_[1].carryAfter = actions_[3].carryAfter = -1;
            actionCount_ = 4;
            actionIndex_ = 0;
            settleStartMs_ = 0;
            target_ = actions_[0].pose;
            armSpeed_ = 1.0f;
            (void)nowMs;
            return;
        }
    }

    void runPlan(uint32_t nowMs) {
        target_ = actions_[actionIndex_].pose;
        if (!wheelsStopped() || !poseReached(pose_, target_)) {
            settleStartMs_ = 0;
            return;
        }
        if (settleStartMs_ == 0) settleStartMs_ = nowMs ? nowMs : 1;
        if (nowMs - settleStartMs_ < ACTION_SETTLE_MS) return;
        if (actions_[actionIndex_].carryAfter >= 0) carrying_ = actions_[actionIndex_].carryAfter == 1;
        settleStartMs_ = 0;
        if (++actionIndex_ < actionCount_) return;
        stepDone(true, "");
        ++stepIndex_;
        beginStep(nowMs);
    }

    void finishPlan() {
        running_ = false;
        target_ = homePose();
        if (linkUp_) event("plan_finished", "");
        else finishedOffline_ = true;
    }

    // ---- wheels -------------------------------------------------------------------------------
    static float clampWheel(float v) { return !(v == v) ? 0.0f : (v < -1.0f ? -1.0f : (v > 1.0f ? 1.0f : v)); }
    bool wheelsStopped() const { return fabsf(appliedLeft_) <= WHEEL_STOPPED && fabsf(appliedRight_) <= WHEEL_STOPPED; }

    void hardStopWheels() {
        desiredLeft_ = desiredRight_ = appliedLeft_ = appliedRight_ = 0.0f;
        hw_.setWheels(0.0f, 0.0f);
    }

    static float rampOne(float applied, float desired, float maxStep) {
        float aim = (applied * desired < 0.0f && fabsf(applied) > WHEEL_STOPPED) ? 0.0f : desired;  // stop before reversing
        float delta = aim - applied;
        if (delta > maxStep) delta = maxStep;
        if (delta < -maxStep) delta = -maxStep;
        float next = applied + delta;
        return (aim == 0.0f && fabsf(next) <= WHEEL_STOPPED) ? 0.0f : next;
    }

    void rampWheels(float dt) {
        bool armBusy = !poseReached(pose_, target_);
        float left = armBusy ? 0.0f : desiredLeft_;  // the wheels wait for the arm to settle
        float right = armBusy ? 0.0f : desiredRight_;
        appliedLeft_ = rampOne(appliedLeft_, left, WHEEL_RAMP_PER_S * dt);
        appliedRight_ = rampOne(appliedRight_, right, WHEEL_RAMP_PER_S * dt);
    }

    void limitForObstacles() {
        if (desiredLeft_ <= 0.0f && desiredRight_ <= 0.0f) {
            obstacleSeen_ = false;
            return;
        }
        SensorReadings s = hw_.readSensors();
        if (s.obstacleLeft != 1 && s.obstacleRight != 1) {
            obstacleSeen_ = false;
            return;
        }
        if (desiredLeft_ > 0.0f) desiredLeft_ = 0.0f;
        if (desiredRight_ > 0.0f) desiredRight_ = 0.0f;
        if (!obstacleSeen_) {
            obstacleSeen_ = true;
            event("obstacle", s.obstacleLeft == 1 ? "left" : "right");
        }
    }

    // ---- watchdogs ----------------------------------------------------------------------------
    void checkLink(uint32_t nowMs) {
        if (!linkUp_ || nowMs - lastPingMs_ <= LINK_TIMEOUT_MS) return;
        linkUp_ = false;
        event("link_lost", "");
        if (!running_) {  // no plan running: stop the wheels and hold the arm
            hardStopWheels();
            target_ = pose_;
        }
    }

    void checkBattery() {
        float volts = hw_.batteryVolts();
        if (!isfinite(volts)) return;
        batteryV_ = isfinite(batteryV_) ? batteryV_ + BATTERY_SMOOTHING * (volts - batteryV_) : volts;
        char detail[24];
        snprintf(detail, sizeof detail, "%.2f V", batteryV_);
        if (batteryV_ >= BATTERY_CLEAR_V) {
            batteryWarned_ = batteryStopped_ = false;
        } else if (batteryV_ < BATTERY_STOP_V && !batteryStopped_) {
            batteryStopped_ = batteryWarned_ = true;
            hardStopWheels();
            target_ = pose_;
            running_ = false;
            event("battery_critical", detail);
        } else if (batteryV_ < BATTERY_WARN_V && !batteryWarned_) {
            batteryWarned_ = true;
            event("battery_low", detail);
        }
    }

    RoverHardware& hw_;
    RoverSink& sink_;
    uint32_t startMs_, lastTickMs_;
    Pose pose_, target_;
    float armSpeed_;
    bool autoMode_;
    float desiredLeft_, desiredRight_, appliedLeft_, appliedRight_;
    bool linkUp_;
    uint32_t lastPingMs_;
    bool finishedOffline_;
    long storedPlanId_;
    PlanStep steps_[MAX_PLAN_STEPS];
    int stepCount_;
    bool running_;
    int stepIndex_;
    Action actions_[4];
    int actionCount_, actionIndex_;
    uint32_t settleStartMs_;
    long currentStepId_;
    bool carrying_;
    float batteryV_;
    bool batteryWarned_, batteryStopped_;
    bool obstacleStop_ = false, obstacleSeen_ = false;
    uint32_t nextStateMs_, nextSensorsMs_;
};
