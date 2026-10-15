#pragma once

// Pin plan for the ESP32-S3-WROOM-1 N16R8 board with the built-in camera socket.
//
// The camera wiring below is CONFIRMED on this board: firmware/cam_probe.txt found a sensor on
// clock 15, bus 4 and 5 (the same map as Espressif's ESP32-S3-EYE), and the board's own pin legend
// marks the same 14 pins as camera. Everything else is still untested on the bench.
//
// Not usable for anything else on this board:
//   35, 36, 37   octal PSRAM (N16R8)
//   19, 20       native USB
//   43, 44       UART0 (serial console)
//   0            BOOT button
//   3, 45, 46    strapping pins, read ONCE at reset. NEVER put I2C on them: the servo driver board pulls
//                SDA and SCL high, and a high GPIO45 at reset sets the flash voltage wrong, so the board
//                resets over and over with only the ROM boot lines on the serial port. Use 46 only for an
//                input that is quiet (low or unplugged) while the board starts.
//   38, 39, 40   microSD slot. Each has a pull-up resistor on the board, so they suit inputs and
//                the I2C bus, but NOT motor driver inputs (those would be held high at reset).
//                Leave the SD slot empty.

// ---- Camera (taken: GPIO 4 to 13, 15 to 18) ---------------------------------------------
constexpr int CAM_PIN_PWDN = -1;
constexpr int CAM_PIN_RESET = -1;
constexpr int CAM_PIN_XCLK = 15;
constexpr int CAM_PIN_SIOD = 4;   // camera control bus (SDA)
constexpr int CAM_PIN_SIOC = 5;   // camera control bus (SCL)
constexpr int CAM_PIN_D0 = 11;    // Y2
constexpr int CAM_PIN_D1 = 9;     // Y3
constexpr int CAM_PIN_D2 = 8;     // Y4
constexpr int CAM_PIN_D3 = 10;    // Y5
constexpr int CAM_PIN_D4 = 12;    // Y6
constexpr int CAM_PIN_D5 = 18;    // Y7
constexpr int CAM_PIN_D6 = 17;    // Y8
constexpr int CAM_PIN_D7 = 16;    // Y9
constexpr int CAM_PIN_VSYNC = 6;
constexpr int CAM_PIN_HREF = 7;
constexpr int CAM_PIN_PCLK = 13;

// ---- I2C bus for the PCA9685 servo driver (a second bus, apart from the camera's) --------
// On the SD slot pins, which already have pull-ups on the board. The camera already uses I2C
// port 0 (Wire), so the PCA9685 code must use Wire1: Wire1.begin(PIN_I2C_SDA, PIN_I2C_SCL).
constexpr int PIN_I2C_SDA = 39;
constexpr int PIN_I2C_SCL = 40;

// PCA9685 channels for the arm
constexpr int SERVO_CH_BASE = 0;
constexpr int SERVO_CH_SHOULDER = 1;
constexpr int SERVO_CH_ELBOW = 2;
constexpr int SERVO_CH_GRIPPER = 3;

// ---- L298N motor driver -------------------------------------------------------------------
// All six sit on pins with nothing else attached. Fit a 10k pull-down on each input so the
// wheels stay still while the board resets.
constexpr int PIN_MOTOR_L_EN = 38;   // ENA, speed
constexpr int PIN_MOTOR_L_IN1 = 2;
constexpr int PIN_MOTOR_L_IN2 = 47;
constexpr int PIN_MOTOR_R_EN = 48;   // ENB, speed; also drives the board's RGB LED, which will flicker
constexpr int PIN_MOTOR_R_IN1 = 21;
constexpr int PIN_MOTOR_R_IN2 = 14;

// ---- Sensors ------------------------------------------------------------------------------
constexpr int PIN_IR_OBSTACLE_L = -1;  // SD slot pin, has a board pull-up: fine for an input
constexpr int PIN_IR_OBSTACLE_R = -1;
constexpr int PIN_IR_FLAME_L = 46;     // strapping pin: input only, check that the board still boots
constexpr int PIN_IR_FLAME_R = -1;     // no free pin left for a second flame sensor
constexpr int PIN_DHT = -1;            // no free pin left; the DHT11 only reads room temperature

// Pack voltage: 2S pack positive -> 100k -> this pin -> 33k -> GND (see docs/power.md).
// GPIO 1 is on ADC1, which keeps working while Wi-Fi is on (ADC2 does not).
constexpr int PIN_BATT_ADC = 1;

// Set this to true ONLY once the 100k and 33k divider is wired and the `batt` command in
// bringup.txt shows a sensible voltage. While it is false the firmware reports battery_v as null
// and the low-battery guard (warn below 6.8 V, stop the motors below 6.4 V) stays out of the way,
// because a floating pin would read garbage and could stop a healthy rover.
constexpr bool BATTERY_DIVIDER_FITTED = false;
constexpr float BATTERY_DIVIDER_TOP_K = 100.0f;
constexpr float BATTERY_DIVIDER_BOTTOM_K = 33.0f;

// The arm's servos stay unpowered at boot and come on the first time the arm is asked to move away
// from the home pose, so a rover that is switched on never jerks by itself. Set true to power them
// at boot instead (they will then jump to the home pose).
constexpr bool ARM_POWER_ON_AT_BOOT = false;

// Stop forward driving while an IR obstacle sensor is tripped (reversing stays allowed). Turn this on
// only after `sensors` in bringup.txt shows each module reads 0 when something is in front of it and
// 1 when clear. If a module reads the other way round the rover could never drive forward.
constexpr bool IR_OBSTACLE_STOP_ENABLED = false;
