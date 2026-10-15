#include "hardware.h"

#include <DHT.h>
#include <Wire.h>

#include "pins.h"

// ---- what is ASSUMED and must be checked at the bench -----------------------------------------
// 1. How each joint's angle turns into a servo pulse (SERVOS below). The numbers assume ordinary
//    servos on 600 to 2400 microseconds, the elbow on a 270 degree servo on 500 to 2500, and every
//    joint turning the same way as the angle. Wrong direction or range: change `direction` and
//    `centreAngle`. Do this with the arm held clear, one joint at a time (firmware/bringup.txt).
// 2. The wheel PWM frequency (1 kHz) suits the L298N. The motor direction wires may need swapping.
// 3. IR sensor modules read LOW when triggered (most do). Check with `sensors` in bringup.txt.
// 4. The servo power is NOT switched on at boot. It comes on the first time the arm is asked to
//    move away from the home pose, so a powered-up rover never jerks to a pose by itself.

namespace {

constexpr uint8_t PCA_ADDRESS = 0x40;
constexpr uint32_t PCA_RETRY_MS = 2000;
constexpr float SERVO_FRAME_US = 20000.0f;  // 50 Hz
constexpr int WHEEL_PWM_LEFT = 2;           // LEDC channels 2 and 3 are on a different timer from the camera clock (channel 0)
constexpr int WHEEL_PWM_RIGHT = 3;
constexpr int WHEEL_PWM_HZ = 1000;
constexpr int WHEEL_PWM_BITS = 8;
constexpr uint32_t DHT_PERIOD_MS = 2500;
constexpr int ADC_SAMPLES = 8;

struct JointServo {
    uint8_t channel;
    float centreAngle;  // the protocol angle that gets the middle pulse
    float direction;    // +1 or -1: which way the servo turns for a rising angle
    float centreUs;
    float usPerDegree;
    float minUs, maxUs;  // never ask for a pulse outside this
};

// ASSUMED. See the note at the top of this file.
const JointServo SERVOS[JOINT_COUNT] = {
    {SERVO_CH_BASE, 0.0f, +1.0f, 1500.0f, 10.0f, 600.0f, 2400.0f},
    {SERVO_CH_SHOULDER, 60.0f, +1.0f, 1500.0f, 10.0f, 600.0f, 2400.0f},
    {SERVO_CH_ELBOW, 0.0f, +1.0f, 1500.0f, 7.41f, 500.0f, 2500.0f},
    {SERVO_CH_GRIPPER, 45.0f, +1.0f, 1500.0f, 10.0f, 600.0f, 2400.0f},
};

DHT* g_dht = nullptr;

void pcaWrite(uint8_t reg, uint8_t value) {
    Wire1.beginTransmission(PCA_ADDRESS);
    Wire1.write(reg);
    Wire1.write(value);
    Wire1.endTransmission();
}

bool pcaBegin() {
    Wire1.begin(PIN_I2C_SDA, PIN_I2C_SCL, 400000);
    Wire1.beginTransmission(PCA_ADDRESS);
    if (Wire1.endTransmission() != 0) return false;
    pcaWrite(0x00, 0x10);  // sleep, so the frequency can be set
    pcaWrite(0xFE, 121);   // 50 Hz: 25 MHz / (4096 * 50) - 1
    pcaWrite(0x00, 0x20);  // wake, auto-increment on
    delay(5);
    pcaWrite(0x00, 0xA0);  // restart
    return true;
}

void pcaSetTicks(int channel, int onTicks, int offTicks) {
    Wire1.beginTransmission(PCA_ADDRESS);
    Wire1.write(0x06 + 4 * channel);
    Wire1.write(onTicks & 0xFF);
    Wire1.write(onTicks >> 8);
    Wire1.write(offTicks & 0xFF);
    Wire1.write(offTicks >> 8);
    Wire1.endTransmission();
}

void setMotor(int enPin, int in1, int in2, int pwmChannel, float speed) {
    int duty = static_cast<int>(fabsf(speed) * 255.0f + 0.5f);
    if (duty > 255) duty = 255;
    if (duty == 0) {
        digitalWrite(in1, LOW);  // both low lets the motor coast to a stop
        digitalWrite(in2, LOW);
        ledcWrite(pwmChannel, 0);
        return;
    }
    digitalWrite(in1, speed > 0 ? HIGH : LOW);
    digitalWrite(in2, speed > 0 ? LOW : HIGH);
    ledcWrite(pwmChannel, duty);
    (void)enPin;
}

int readActiveLow(int pin) {
    if (pin < 0) return -1;
    return digitalRead(pin) == LOW ? 1 : 0;
}

}  // namespace

void roverPinsSafeState() {
    const int outputs[] = {PIN_MOTOR_L_EN, PIN_MOTOR_L_IN1, PIN_MOTOR_L_IN2, PIN_MOTOR_R_EN, PIN_MOTOR_R_IN1, PIN_MOTOR_R_IN2};
    for (int pin : outputs) {
        pinMode(pin, OUTPUT);
        digitalWrite(pin, LOW);
    }
}

void ArduinoRoverHardware::begin() {
    roverPinsSafeState();
    ledcSetup(WHEEL_PWM_LEFT, WHEEL_PWM_HZ, WHEEL_PWM_BITS);
    ledcSetup(WHEEL_PWM_RIGHT, WHEEL_PWM_HZ, WHEEL_PWM_BITS);
    ledcAttachPin(PIN_MOTOR_L_EN, WHEEL_PWM_LEFT);
    ledcAttachPin(PIN_MOTOR_R_EN, WHEEL_PWM_RIGHT);
    ledcWrite(WHEEL_PWM_LEFT, 0);
    ledcWrite(WHEEL_PWM_RIGHT, 0);
    const int inputs[] = {PIN_IR_OBSTACLE_L, PIN_IR_OBSTACLE_R, PIN_IR_FLAME_L, PIN_IR_FLAME_R};
    for (int pin : inputs) {
        if (pin >= 0) pinMode(pin, INPUT);
    }
    if (PIN_DHT >= 0) {
        g_dht = new DHT(PIN_DHT, DHT11);
        g_dht->begin();
    }
    if (BATTERY_DIVIDER_FITTED) analogReadResolution(12);
}

void ArduinoRoverHardware::setWheels(float left, float right) {
    if (left != lastLeft_) {
        setMotor(PIN_MOTOR_L_EN, PIN_MOTOR_L_IN1, PIN_MOTOR_L_IN2, WHEEL_PWM_LEFT, left);
        lastLeft_ = left;
    }
    if (right != lastRight_) {
        setMotor(PIN_MOTOR_R_EN, PIN_MOTOR_R_IN1, PIN_MOTOR_R_IN2, WHEEL_PWM_RIGHT, right);
        lastRight_ = right;
    }
}

bool ArduinoRoverHardware::ensureServoDriver() {
    if (servoDriverReady_) return true;
    uint32_t now = millis();
    if (servoRetryAt_ != 0 && static_cast<int32_t>(now - servoRetryAt_) < 0) return false;
    servoRetryAt_ = now + PCA_RETRY_MS;
    servoDriverReady_ = pcaBegin();
    if (!servoDriverReady_) Serial.println("arm: servo driver (PCA9685, 0x40) not found. Check SDA/SCL, 3V3 and GND. Will retry.");
    return servoDriverReady_;
}

void ArduinoRoverHardware::writeServo(int joint, float angle) {
    const JointServo& s = SERVOS[joint];
    float us = s.centreUs + s.direction * (angle - s.centreAngle) * s.usPerDegree;
    if (us < s.minUs) us = s.minUs;
    if (us > s.maxUs) us = s.maxUs;
    pcaSetTicks(s.channel, 0, static_cast<int>(us * 4096.0f / SERVO_FRAME_US));
}

void ArduinoRoverHardware::setJoints(const Pose& pose) {
    if (!armEnabled_) {
        const Pose home = homePose();
        bool atHome = true;
        for (int j = 0; j < JOINT_COUNT; ++j) {
            if (fabsf(pose.angle[j] - home.angle[j]) > 0.01f) atHome = false;
        }
        if (atHome && !ARM_POWER_ON_AT_BOOT) return;  // stay limp until the arm is really asked to move
        armEnabled_ = true;
    }
    if (!ensureServoDriver()) return;
    for (int j = 0; j < JOINT_COUNT; ++j) {
        if (isnan(lastAngle_[j]) || fabsf(pose.angle[j] - lastAngle_[j]) >= 0.05f) {
            writeServo(j, pose.angle[j]);
            lastAngle_[j] = pose.angle[j];
        }
    }
}

SensorReadings ArduinoRoverHardware::readSensors() {
    SensorReadings s;
    s.obstacleLeft = readActiveLow(PIN_IR_OBSTACLE_L);
    s.obstacleRight = readActiveLow(PIN_IR_OBSTACLE_R);
    s.flameLeft = readActiveLow(PIN_IR_FLAME_L);
    s.flameRight = readActiveLow(PIN_IR_FLAME_R);
    if (g_dht != nullptr) {
        uint32_t now = millis();
        if (static_cast<int32_t>(now - nextDhtAt_) >= 0) {
            nextDhtAt_ = now + DHT_PERIOD_MS;
            temp_ = g_dht->readTemperature();
            humidity_ = g_dht->readHumidity();
        }
        s.tempC = temp_;
        s.humPct = humidity_;
    }
    return s;
}

float ArduinoRoverHardware::batteryVolts() {
    if (!BATTERY_DIVIDER_FITTED) return NAN;  // no divider, so no reading, so the guard stays out of the way
    uint32_t sum = 0;
    for (int i = 0; i < ADC_SAMPLES; ++i) sum += analogReadMilliVolts(PIN_BATT_ADC);
    float pinVolts = sum / static_cast<float>(ADC_SAMPLES) / 1000.0f;
    if (pinVolts < 0.3f) return NAN;  // nothing connected to the pin
    return pinVolts * (BATTERY_DIVIDER_TOP_K + BATTERY_DIVIDER_BOTTOM_K) / BATTERY_DIVIDER_BOTTOM_K;
}
