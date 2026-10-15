#pragma once

#include <Arduino.h>

#include "rover_core.h"

// The real rover's parts, behind the RoverHardware interface: L298N wheels (PWM on the EN pins),
// the PCA9685 servo driver on I2C port 1, the IR sensors, the DHT11 and the pack-voltage divider.
// All pins come from pins.h. NOT TESTED ON THE BOARD YET: every number marked ASSUMED in
// hardware.cpp has to be checked at the bench (see firmware/bringup.txt).

// Call as the very FIRST thing in setup(), before Wi-Fi and the camera: every motor pin goes low so
// the wheels cannot move while the rest of the system starts.
void roverPinsSafeState();

class ArduinoRoverHardware : public RoverHardware {
public:
    void begin();  // sets up the PWM, the sensor pins and the voltage input
    void setWheels(float left, float right) override;
    void setJoints(const Pose& pose) override;
    SensorReadings readSensors() override;
    float batteryVolts() override;

private:
    bool ensureServoDriver();
    void writeServo(int joint, float angle);

    bool armEnabled_ = false;      // the servos stay unpowered until the arm is first asked to move
    bool servoDriverReady_ = false;
    uint32_t servoRetryAt_ = 0;
    float lastAngle_[JOINT_COUNT] = {NAN, NAN, NAN, NAN};
    float lastLeft_ = NAN, lastRight_ = NAN;
    float temp_ = NAN, humidity_ = NAN;
    uint32_t nextDhtAt_ = 0;
};
