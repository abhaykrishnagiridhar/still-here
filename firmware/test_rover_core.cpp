// Tests for rover_core.h on the PC, with a fake rover and a fake operator:
//   g++ -std=c++11 -Wall -Wextra -Wpedantic test_rover_core.cpp -o test_rover_core && ./test_rover_core
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <string>
#include <vector>

#include "rover_core.h"

static int failures = 0;

#define CHECK(cond)                                                            \
    do {                                                                       \
        if (!(cond)) {                                                         \
            std::fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #cond);       \
            ++failures;                                                        \
        }                                                                      \
    } while (0)

static bool near(double a, double b, double tol = 0.01) { return std::fabs(a - b) <= tol; }

// ---- fakes -------------------------------------------------------------------------------------

struct FakeHardware : RoverHardware {
    float left = 0, right = 0;
    Pose joints = homePose();
    float volts = NAN;
    SensorReadings sensors;
    float maxWheelStep = 0;       // biggest change in a wheel command between two calls
    float maxJointStep[JOINT_COUNT] = {0, 0, 0, 0};
    bool wheelsAndArmMovedTogether = false;
    bool first = true;

    void setWheels(float l, float r) override {
        maxWheelStep = std::fmax(maxWheelStep, std::fmax(std::fabs(l - left), std::fabs(r - right)));
        left = l;
        right = r;
    }
    void setJoints(const Pose& pose) override {
        bool armMoved = false;
        for (int j = 0; j < JOINT_COUNT; ++j) {
            float step = std::fabs(pose.angle[j] - joints.angle[j]);
            maxJointStep[j] = std::fmax(maxJointStep[j], step);
            if (step > 1e-6f) armMoved = true;
        }
        if (armMoved && (std::fabs(left) > WHEEL_STOPPED || std::fabs(right) > WHEEL_STOPPED)) wheelsAndArmMovedTogether = true;
        joints = pose;
    }
    SensorReadings readSensors() override { return sensors; }
    float batteryVolts() override { return volts; }
};

struct RecordingSink : RoverSink {
    std::vector<std::string> sent;
    void send(const char* json) override { sent.push_back(json); }
    int count(const std::string& needle) const {
        int n = 0;
        for (const std::string& s : sent) n += s.find(needle) != std::string::npos;
        return n;
    }
    bool has(const std::string& needle) const { return count(needle) > 0; }
    int firstIndex(const std::string& needle) const {
        for (size_t i = 0; i < sent.size(); ++i) {
            if (sent[i].find(needle) != std::string::npos) return static_cast<int>(i);
        }
        return -1;
    }
    std::string last(const std::string& needle) const {
        for (size_t i = sent.size(); i-- > 0;) {
            if (sent[i].find(needle) != std::string::npos) return sent[i];
        }
        return "";
    }
    void clear() { sent.clear(); }
};

struct Rig {
    FakeHardware hw;
    RecordingSink sink;
    RoverCore core;
    uint32_t now = 1000;
    Rig() : core(hw, sink) { core.begin(now); }

    void send(const std::string& json) {
        Command command;
        ParseStatus status = parseCommand(json.c_str(), json.size(), &command);
        if (status == PARSE_OK) core.handle(command, now);
    }
    // Runs the rover for ms milliseconds, one tick per 10 ms, pinging every 500 ms when asked.
    void run(uint32_t ms, bool ping = true) {
        for (uint32_t t = 0; t < ms; t += 10) {
            now += 10;
            if (ping && (now % 500) < 10) send("{\"type\":\"ping\"}");
            core.tick(now);
        }
    }
};

static const char* PLAN_TWO_STEPS =
    "{\"type\":\"plan\",\"plan_id\":7,\"steps\":["
    "{\"id\":1,\"action\":\"pick\",\"x\":150,\"y\":0,\"z\":20},"
    "{\"id\":2,\"action\":\"drop\",\"x\":100,\"y\":-80,\"z\":20}]}";

// ---- start up and the wheels ---------------------------------------------------------------------

static void the_wheels_start_stopped_and_the_arm_at_home() {
    Rig r;
    CHECK(r.hw.left == 0 && r.hw.right == 0);
    CHECK(near(r.hw.joints.angle[JOINT_SHOULDER], 60));
}

static void the_wheels_ramp_up_over_about_200_ms_and_never_jump() {
    Rig r;
    r.send("{\"type\":\"drive\",\"left\":1,\"right\":1}");
    r.run(30);
    CHECK(r.core.wheelLeft() > 0.0f && r.core.wheelLeft() < 0.5f);
    r.run(300);
    CHECK(near(r.core.wheelLeft(), 1.0));
    CHECK(r.hw.maxWheelStep <= WHEEL_RAMP_PER_S * 0.011f);
}

static void wheel_speeds_are_held_inside_minus_one_and_one() {
    Rig r;
    r.send("{\"type\":\"drive\",\"left\":9,\"right\":-9}");
    r.run(600);
    CHECK(near(r.core.wheelLeft(), 1.0) && near(r.core.wheelRight(), -1.0));
}

static void the_wheels_stop_before_they_reverse() {
    Rig r;
    r.send("{\"type\":\"drive\",\"left\":1,\"right\":1}");
    r.run(400);
    r.send("{\"type\":\"drive\",\"left\":-1,\"right\":-1}");
    bool crossedZeroSmoothly = true;
    float previous = r.core.wheelLeft();
    for (int i = 0; i < 100; ++i) {
        r.run(10);
        if (std::fabs(r.core.wheelLeft() - previous) > WHEEL_RAMP_PER_S * 0.011f) crossedZeroSmoothly = false;
        previous = r.core.wheelLeft();
    }
    CHECK(crossedZeroSmoothly);
    CHECK(near(r.core.wheelLeft(), -1.0));
}

// ---- the arm --------------------------------------------------------------------------------------

static void the_arm_moves_no_faster_than_its_speed_limit() {
    Rig r;
    r.send("{\"type\":\"arm_pose\",\"base\":90,\"shoulder\":60,\"elbow\":-90,\"gripper\":90,\"speed\":1}");
    r.run(100);
    CHECK(r.hw.maxJointStep[JOINT_BASE] <= SERVO_RATE_DPS * 0.011f);
    r.run(1000);
    CHECK(near(r.core.pose().angle[JOINT_BASE], 90, 0.1));
}

static void a_slower_arm_move_is_slower() {
    Rig r;
    r.send("{\"type\":\"arm_pose\",\"base\":90,\"speed\":0.25}");
    r.run(500);
    CHECK(r.core.pose().angle[JOINT_BASE] < 20.0f);
}

static void the_arm_never_goes_past_its_limits() {
    Rig r;
    r.send("{\"type\":\"arm_pose\",\"base\":500,\"shoulder\":-50,\"elbow\":400,\"gripper\":200}");
    r.run(3000);
    const Pose& p = r.core.pose();
    CHECK(near(p.angle[JOINT_BASE], 90) && near(p.angle[JOINT_SHOULDER], 0));
    CHECK(near(p.angle[JOINT_ELBOW], 135) && near(p.angle[JOINT_GRIPPER], 90));
}

static void a_joint_the_message_does_not_mention_stays_where_it_was() {
    Rig r;
    r.send("{\"type\":\"arm_pose\",\"base\":40}");
    r.run(2000);
    CHECK(near(r.core.pose().angle[JOINT_ELBOW], -90) && near(r.core.pose().angle[JOINT_BASE], 40, 0.1));
}

static void a_new_drive_command_while_the_arm_moves_holds_the_arm() {
    Rig r;
    r.send("{\"type\":\"arm_pose\",\"base\":90}");
    r.run(100);
    float at = r.core.pose().angle[JOINT_BASE];
    r.send("{\"type\":\"drive\",\"left\":1,\"right\":1}");
    r.run(500);
    CHECK(near(r.core.pose().angle[JOINT_BASE], at, 0.5));
    CHECK(r.core.wheelLeft() > 0.5f);
}

static void a_new_arm_command_while_driving_stops_the_wheels_first() {
    Rig r;
    r.send("{\"type\":\"drive\",\"left\":1,\"right\":1}");
    r.run(400);
    r.send("{\"type\":\"arm_pose\",\"base\":60}");
    r.run(1500);
    CHECK(r.core.wheelLeft() == 0.0f);
    CHECK(near(r.core.pose().angle[JOINT_BASE], 60, 0.1));
    CHECK(!r.hw.wheelsAndArmMovedTogether);
}

// ---- link loss and abort --------------------------------------------------------------------------

static void with_no_plan_two_seconds_of_silence_stops_the_wheels_and_holds_the_arm() {
    Rig r;
    r.send("{\"type\":\"drive\",\"left\":1,\"right\":1}");
    r.run(1000);  // pinged
    CHECK(r.core.wheelLeft() > 0.9f);
    r.run(2600, false);  // no more pings
    CHECK(r.core.wheelLeft() == 0.0f && r.hw.left == 0.0f);
    CHECK(!r.core.linkUp());
    CHECK(r.sink.count("\"code\":\"link_lost\"") == 1);
}

static void a_ping_after_a_lost_link_restores_it_once() {
    Rig r;
    r.run(2600, false);
    r.send("{\"type\":\"ping\"}");
    r.send("{\"type\":\"ping\"}");
    CHECK(r.core.linkUp());
    CHECK(r.sink.count("\"code\":\"link_restored\"") == 1);
}

static void abort_stops_the_wheels_at_once_and_holds_the_arm() {
    Rig r;
    r.send("{\"type\":\"drive\",\"left\":1,\"right\":1}");
    r.run(500);
    r.send("{\"type\":\"arm_pose\",\"base\":90}");  // (stops wheels, starts the arm)
    r.send("{\"type\":\"abort\"}");
    CHECK(r.core.wheelLeft() == 0.0f);
    float at = r.core.pose().angle[JOINT_BASE];
    r.run(500);
    CHECK(near(r.core.pose().angle[JOINT_BASE], at, 0.01));
    CHECK(r.sink.has("\"code\":\"aborted\""));
}

static void unknown_and_unreadable_messages_change_nothing() {
    Rig r;
    r.send("{\"type\":\"something_new\"}");
    r.send("not json at all");
    r.send("{\"type\":\"drive\",\"left\":\"fast\",\"right\":0}");
    r.run(300);
    CHECK(r.core.wheelLeft() == 0.0f);
    CHECK(r.sink.count("\"type\":\"event\"") == 0);
}

// ---- plans ----------------------------------------------------------------------------------------

static void a_good_plan_is_stored_and_confirmed() {
    Rig r;
    r.send(PLAN_TWO_STEPS);
    CHECK(r.sink.has("\"code\":\"plan_stored\",\"detail\":\"2 steps\""));
    CHECK(r.core.storedPlanId() == 7);
    r.run(250);
    CHECK(r.sink.last("\"type\":\"state\"").find("\"plan_id\":7") != std::string::npos);
}

static void a_bad_plan_is_refused_and_the_old_one_is_kept() {
    Rig r;
    r.send(PLAN_TWO_STEPS);
    r.sink.clear();
    r.send("{\"type\":\"plan\",\"plan_id\":8,\"steps\":[{\"id\":1,\"action\":\"juggle\",\"x\":1,\"y\":2,\"z\":3}]}");
    CHECK(r.sink.has("\"code\":\"bad_plan\",\"detail\":\"unknown action\""));
    r.send("{\"type\":\"plan\",\"plan_id\":\"run-1\",\"steps\":[]}");
    r.send("{\"type\":\"plan\",\"plan_id\":9,\"steps\":[{\"id\":1}]}");
    CHECK(r.sink.count("\"code\":\"bad_plan\"") == 3);
    CHECK(r.core.storedPlanId() == 7);
}

static void starting_a_plan_that_was_never_stored_is_refused() {
    Rig r;
    r.send("{\"type\":\"plan_start\",\"plan_id\":1}");
    CHECK(r.sink.has("\"code\":\"bad_plan\",\"detail\":\"no stored plan with that id\""));
    r.send(PLAN_TWO_STEPS);
    r.send("{\"type\":\"plan_start\",\"plan_id\":99}");
    CHECK(!r.core.planRunning());
}

static void a_stored_plan_runs_both_steps_reports_them_and_finishes() {
    Rig r;
    r.send(PLAN_TWO_STEPS);
    r.send("{\"type\":\"plan_start\",\"plan_id\":7}");
    CHECK(r.core.planRunning());
    r.run(20000);
    CHECK(!r.core.planRunning());
    CHECK(r.sink.has("\"plan_id\":7,\"step_id\":1,\"ok\":true,\"reason\":\"\""));
    CHECK(r.sink.has("\"plan_id\":7,\"step_id\":2,\"ok\":true,\"reason\":\"\""));
    CHECK(r.sink.firstIndex("\"step_id\":1") < r.sink.firstIndex("\"step_id\":2"));
    CHECK(r.sink.has("\"code\":\"plan_finished\""));
    CHECK(near(r.core.pose().angle[JOINT_SHOULDER], 60, 0.5));  // back home
    CHECK(!r.core.carrying());
}

static void the_status_says_running_then_holding_a_block_then_idle() {
    Rig r;
    r.send(PLAN_TWO_STEPS);
    r.send("{\"type\":\"plan_start\",\"plan_id\":7}");
    r.run(400);
    CHECK(r.sink.last("\"type\":\"state\"").find("\"status\":\"running\"") != std::string::npos);
    CHECK(r.sink.last("\"type\":\"state\"").find("\"step_id\":1") != std::string::npos);
    r.run(20000);
    CHECK(r.sink.last("\"type\":\"state\"").find("\"status\":\"idle\"") != std::string::npos);
    CHECK(r.sink.last("\"type\":\"state\"").find("\"step_id\":null") != std::string::npos);
}

static void the_block_is_marked_as_carried_between_the_pick_and_the_drop() {
    Rig r;
    r.send(PLAN_TWO_STEPS);
    r.send("{\"type\":\"plan_start\",\"plan_id\":7}");
    bool wasCarrying = false;
    for (int i = 0; i < 2000; ++i) {
        r.run(10);
        if (r.core.carrying()) wasCarrying = true;
    }
    CHECK(wasCarrying);
}

static void a_step_out_of_reach_is_reported_and_the_plan_goes_on() {
    Rig r;
    r.send("{\"type\":\"plan\",\"plan_id\":3,\"steps\":[{\"id\":1,\"action\":\"pick\",\"x\":900,\"y\":0,\"z\":20},"
           "{\"id\":2,\"action\":\"drop\",\"x\":100,\"y\":-80,\"z\":20}]}");
    r.send("{\"type\":\"plan_start\",\"plan_id\":3}");
    r.run(20000);
    CHECK(r.sink.has("\"step_id\":1,\"ok\":false,\"reason\":\"unreachable\""));
    CHECK(r.sink.has("\"step_id\":2,\"ok\":true"));
    CHECK(r.sink.has("\"code\":\"plan_finished\""));
}

static void an_empty_plan_finishes_at_once() {
    Rig r;
    r.send("{\"type\":\"plan\",\"plan_id\":4,\"steps\":[]}");
    r.send("{\"type\":\"plan_start\",\"plan_id\":4}");
    CHECK(!r.core.planRunning());
    CHECK(r.sink.has("\"code\":\"plan_finished\""));
}

static void drive_and_arm_commands_are_ignored_while_a_plan_runs() {
    Rig r;
    r.send(PLAN_TWO_STEPS);
    r.send("{\"type\":\"plan_start\",\"plan_id\":7}");
    r.send("{\"type\":\"drive\",\"left\":1,\"right\":1}");
    r.run(300);
    CHECK(r.core.wheelLeft() == 0.0f);
    r.send("{\"type\":\"plan\",\"plan_id\":8,\"steps\":[]}");
    CHECK(r.core.storedPlanId() == 7);  // a running plan is not replaced
    CHECK(r.sink.has("\"detail\":\"a plan is running\""));
}

static void abort_ends_a_running_plan() {
    Rig r;
    r.send(PLAN_TWO_STEPS);
    r.send("{\"type\":\"plan_start\",\"plan_id\":7}");
    r.run(500);
    r.send("{\"type\":\"abort\"}");
    CHECK(!r.core.planRunning());
    r.run(2000);
    CHECK(!r.sink.has("\"code\":\"plan_finished\""));
}

static void a_running_plan_carries_on_without_the_link_and_reports_when_it_returns() {
    Rig r;
    r.send(PLAN_TWO_STEPS);
    r.send("{\"type\":\"plan_start\",\"plan_id\":7}");
    r.run(20000, false);  // no pings at all
    CHECK(!r.core.planRunning());
    CHECK(r.sink.has("\"code\":\"link_lost\""));
    CHECK(!r.sink.has("\"code\":\"plan_finished\""));  // nobody to tell yet
    CHECK(r.sink.has("\"step_id\":2,\"ok\":true"));
    r.send("{\"type\":\"ping\"}");
    CHECK(r.sink.firstIndex("link_restored") < r.sink.firstIndex("plan_finished"));
    CHECK(r.sink.has("finished while link was down"));
}

static void the_arm_and_the_wheels_never_move_together_during_a_whole_plan() {
    Rig r;
    r.send("{\"type\":\"drive\",\"left\":1,\"right\":1}");
    r.run(300);
    r.send(PLAN_TWO_STEPS);
    r.send("{\"type\":\"plan_start\",\"plan_id\":7}");
    r.run(20000);
    CHECK(!r.hw.wheelsAndArmMovedTogether);
}

// ---- reports --------------------------------------------------------------------------------------

static void state_goes_out_at_5_hz_and_sensors_at_2_hz() {
    Rig r;
    r.run(4000);
    CHECK(std::abs(r.sink.count("\"type\":\"state\"") - 20) <= 1);
    CHECK(std::abs(r.sink.count("\"type\":\"sensors\"") - 8) <= 1);
}

static void the_state_message_has_the_protocol_shape() {
    Rig r;
    r.run(250);
    std::string s = r.sink.last("\"type\":\"state\"");
    CHECK(s.find("\"mode\":\"manual\"") != std::string::npos);
    CHECK(s.find("\"arm\":{\"base\":0.00,\"shoulder\":60.00,\"elbow\":-90.00,\"gripper\":90.00}") != std::string::npos);
    CHECK(s.find("\"plan_id\":null,\"step_id\":null,\"status\":\"idle\"}") != std::string::npos);
    r.send("{\"type\":\"mode\",\"mode\":\"auto\"}");
    r.run(250);
    CHECK(r.sink.last("\"type\":\"state\"").find("\"mode\":\"auto\"") != std::string::npos);
}

static void sensors_that_are_not_fitted_are_sent_as_null() {
    Rig r;
    r.hw.sensors.obstacleLeft = 0;
    r.hw.sensors.obstacleRight = 1;
    r.hw.sensors.flameLeft = 0;  // right flame sensor and the DHT11 have no pin yet
    r.run(600);
    std::string s = r.sink.last("\"type\":\"sensors\"");
    CHECK(s.find("\"ir_obstacle\":{\"left\":false,\"right\":true}") != std::string::npos);
    CHECK(s.find("\"ir_flame\":{\"left\":false,\"right\":null}") != std::string::npos);
    CHECK(s.find("\"dht\":{\"temp_c\":null,\"hum_pct\":null}") != std::string::npos);
    CHECK(s.find("\"battery_v\":null") != std::string::npos);
}

static void a_dht_reading_is_passed_on() {
    Rig r;
    r.hw.sensors.tempC = 23.5f;
    r.hw.sensors.humPct = 41.0f;
    r.run(600);
    CHECK(r.sink.last("\"type\":\"sensors\"").find("\"dht\":{\"temp_c\":23.50,\"hum_pct\":41.00}") != std::string::npos);
}

// ---- battery --------------------------------------------------------------------------------------

static void a_low_battery_warns_once() {
    Rig r;
    r.hw.volts = 6.7f;
    r.run(2000);
    CHECK(r.sink.count("\"code\":\"battery_low\"") == 1);
    CHECK(!r.core.batteryStopped());
    CHECK(r.sink.last("\"type\":\"sensors\"").find("\"battery_v\":6.70") != std::string::npos);
}

static void a_critical_battery_stops_the_motors_and_refuses_to_move_until_it_recovers() {
    Rig r;
    r.send("{\"type\":\"drive\",\"left\":1,\"right\":1}");
    r.run(400);
    r.hw.volts = 6.2f;
    r.run(200);
    CHECK(r.core.batteryStopped() && r.core.wheelLeft() == 0.0f);
    CHECK(r.sink.count("\"code\":\"battery_critical\"") == 1);
    r.send("{\"type\":\"drive\",\"left\":1,\"right\":1}");
    r.run(300);
    CHECK(r.core.wheelLeft() == 0.0f);
    r.send(PLAN_TWO_STEPS);
    r.send("{\"type\":\"plan_start\",\"plan_id\":7}");
    CHECK(!r.core.planRunning());
    CHECK(r.sink.has("\"detail\":\"battery too low\""));
    r.hw.volts = 6.9f;  // not enough: it must reach the clear level
    r.run(3000);
    CHECK(r.core.batteryStopped());
    r.hw.volts = 7.4f;
    r.run(3000);
    CHECK(!r.core.batteryStopped());
    r.send("{\"type\":\"drive\",\"left\":1,\"right\":1}");
    r.run(400);
    CHECK(r.core.wheelLeft() > 0.5f);
}

static void a_critical_battery_ends_a_running_plan() {
    Rig r;
    r.send(PLAN_TWO_STEPS);
    r.send("{\"type\":\"plan_start\",\"plan_id\":7}");
    r.run(300);
    r.hw.volts = 6.0f;
    r.run(100);
    CHECK(!r.core.planRunning());
}

static void a_battery_that_cannot_be_read_never_stops_the_rover() {
    Rig r;  // volts stays NAN, as when the divider is not fitted
    r.send("{\"type\":\"drive\",\"left\":1,\"right\":1}");
    r.run(1000);
    CHECK(!r.core.batteryStopped() && r.core.wheelLeft() > 0.9f);
}

// ---- time -----------------------------------------------------------------------------------------

static void a_closed_connection_stops_the_wheels_at_once_not_two_seconds_later() {
    Rig r;
    r.send("{\"type\":\"drive\",\"left\":1,\"right\":1}");
    r.run(500);
    CHECK(r.core.wheelLeft() > 0.5f);
    r.core.connectionClosed(r.now);
    r.run(20, false);
    CHECK(r.core.wheelLeft() == 0.0f);
    CHECK(!r.core.linkUp());
}

static void a_closed_connection_does_not_stop_a_running_plan() {
    Rig r;
    r.send(PLAN_TWO_STEPS);
    r.send("{\"type\":\"plan_start\",\"plan_id\":7}");
    r.run(300);
    r.core.connectionClosed(r.now);
    r.run(20000, false);
    CHECK(r.sink.has("\"step_id\":2,\"ok\":true"));
}

// ---- obstacle stop --------------------------------------------------------------------------------

static void the_obstacle_stop_is_off_unless_it_is_turned_on() {
    Rig r;
    r.hw.sensors.obstacleLeft = 1;
    r.send("{\"type\":\"drive\",\"left\":1,\"right\":1}");
    r.run(500);
    CHECK(r.core.wheelLeft() > 0.9f);
}

static void a_tripped_obstacle_sensor_stops_forward_driving_and_says_so_once() {
    Rig r;
    r.core.setObstacleStop(true);
    r.hw.sensors.obstacleRight = 1;
    r.send("{\"type\":\"drive\",\"left\":1,\"right\":1}");
    r.run(500);
    CHECK(r.core.wheelLeft() == 0.0f && r.core.wheelRight() == 0.0f);
    CHECK(r.sink.count("\"code\":\"obstacle\",\"detail\":\"right\"") == 1);
}

static void reversing_away_from_an_obstacle_is_allowed() {
    Rig r;
    r.core.setObstacleStop(true);
    r.hw.sensors.obstacleLeft = 1;
    r.hw.sensors.obstacleRight = 1;
    r.send("{\"type\":\"drive\",\"left\":-1,\"right\":-1}");
    r.run(500);
    CHECK(r.core.wheelLeft() < -0.9f);
}

static void driving_forward_works_again_once_the_obstacle_is_gone() {
    Rig r;
    r.core.setObstacleStop(true);
    r.hw.sensors.obstacleLeft = 1;
    r.send("{\"type\":\"drive\",\"left\":1,\"right\":1}");
    r.run(300);
    r.hw.sensors.obstacleLeft = 0;
    r.send("{\"type\":\"drive\",\"left\":1,\"right\":1}");
    r.run(400);
    CHECK(r.core.wheelLeft() > 0.9f);
}

static void a_sensor_that_is_not_fitted_never_stops_the_rover() {
    Rig r;
    r.core.setObstacleStop(true);  // sensors default to -1: not available
    r.send("{\"type\":\"drive\",\"left\":1,\"right\":1}");
    r.run(500);
    CHECK(r.core.wheelLeft() > 0.9f);
}

static void the_clock_wrapping_around_does_not_upset_anything() {
    Rig r;
    r.now = 0xFFFFFFFFu - 500;
    r.core.begin(r.now);
    r.send("{\"type\":\"drive\",\"left\":1,\"right\":1}");
    r.run(1500);
    CHECK(near(r.core.wheelLeft(), 1.0));
    CHECK(r.core.linkUp());
}

static void a_long_pause_is_not_one_giant_step() {
    Rig r;
    r.send("{\"type\":\"arm_pose\",\"base\":90}");
    r.now += 5000;
    r.core.tick(r.now);  // 5 seconds with no tick
    CHECK(r.core.pose().angle[JOINT_BASE] <= SERVO_RATE_DPS * 0.1f + 0.01f);
}

int main() {
    the_wheels_start_stopped_and_the_arm_at_home();
    the_wheels_ramp_up_over_about_200_ms_and_never_jump();
    wheel_speeds_are_held_inside_minus_one_and_one();
    the_wheels_stop_before_they_reverse();
    the_arm_moves_no_faster_than_its_speed_limit();
    a_slower_arm_move_is_slower();
    the_arm_never_goes_past_its_limits();
    a_joint_the_message_does_not_mention_stays_where_it_was();
    a_new_drive_command_while_the_arm_moves_holds_the_arm();
    a_new_arm_command_while_driving_stops_the_wheels_first();
    with_no_plan_two_seconds_of_silence_stops_the_wheels_and_holds_the_arm();
    a_ping_after_a_lost_link_restores_it_once();
    abort_stops_the_wheels_at_once_and_holds_the_arm();
    unknown_and_unreadable_messages_change_nothing();
    a_good_plan_is_stored_and_confirmed();
    a_bad_plan_is_refused_and_the_old_one_is_kept();
    starting_a_plan_that_was_never_stored_is_refused();
    a_stored_plan_runs_both_steps_reports_them_and_finishes();
    the_status_says_running_then_holding_a_block_then_idle();
    the_block_is_marked_as_carried_between_the_pick_and_the_drop();
    a_step_out_of_reach_is_reported_and_the_plan_goes_on();
    an_empty_plan_finishes_at_once();
    drive_and_arm_commands_are_ignored_while_a_plan_runs();
    abort_ends_a_running_plan();
    a_running_plan_carries_on_without_the_link_and_reports_when_it_returns();
    the_arm_and_the_wheels_never_move_together_during_a_whole_plan();
    state_goes_out_at_5_hz_and_sensors_at_2_hz();
    the_state_message_has_the_protocol_shape();
    sensors_that_are_not_fitted_are_sent_as_null();
    a_dht_reading_is_passed_on();
    a_low_battery_warns_once();
    a_critical_battery_stops_the_motors_and_refuses_to_move_until_it_recovers();
    a_critical_battery_ends_a_running_plan();
    a_battery_that_cannot_be_read_never_stops_the_rover();
    a_closed_connection_stops_the_wheels_at_once_not_two_seconds_later();
    a_closed_connection_does_not_stop_a_running_plan();
    the_obstacle_stop_is_off_unless_it_is_turned_on();
    a_tripped_obstacle_sensor_stops_forward_driving_and_says_so_once();
    reversing_away_from_an_obstacle_is_allowed();
    driving_forward_works_again_once_the_obstacle_is_gone();
    a_sensor_that_is_not_fitted_never_stops_the_rover();
    the_clock_wrapping_around_does_not_upset_anything();
    a_long_pause_is_not_one_giant_step();

    if (failures == 0) {
        std::printf("all tests passed\n");
        return EXIT_SUCCESS;
    }
    std::printf("%d check(s) failed\n", failures);
    return EXIT_FAILURE;
}
