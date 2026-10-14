#pragma once

// Fill in from the hardware design. -1 means "not assigned yet".
// N16R8 note: GPIO 35, 36 and 37 are used by the octal PSRAM, do not assign them.
// The camera ribbon also occupies many pins, check your camera module's pin list.

// I2C bus for the PCA9685 servo driver
constexpr int PIN_I2C_SDA = -1;
constexpr int PIN_I2C_SCL = -1;

// PCA9685 channels for the arm
constexpr int SERVO_CH_BASE = 0;
constexpr int SERVO_CH_SHOULDER = 1;
constexpr int SERVO_CH_ELBOW = 2;
constexpr int SERVO_CH_GRIPPER = 3;

// L298N motor driver
constexpr int PIN_MOTOR_L_IN1 = -1;
constexpr int PIN_MOTOR_L_IN2 = -1;
constexpr int PIN_MOTOR_L_EN = -1;
constexpr int PIN_MOTOR_R_IN1 = -1;
constexpr int PIN_MOTOR_R_IN2 = -1;
constexpr int PIN_MOTOR_R_EN = -1;

// Sensors
constexpr int PIN_IR_OBSTACLE_L = -1;
constexpr int PIN_IR_OBSTACLE_R = -1;
constexpr int PIN_IR_FLAME_L = -1;
constexpr int PIN_IR_FLAME_R = -1;
constexpr int PIN_DHT = -1;
