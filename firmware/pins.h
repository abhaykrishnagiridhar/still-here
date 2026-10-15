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
//   3, 45, 46    strapping pins: avoid, or use only for inputs that are quiet while the board resets
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
constexpr int PIN_MOTOR_L_EN = 41;   // ENA, speed
constexpr int PIN_MOTOR_L_IN1 = 42;
constexpr int PIN_MOTOR_L_IN2 = 47;
constexpr int PIN_MOTOR_R_EN = 48;   // ENB, speed; also drives the board's RGB LED, which will flicker
constexpr int PIN_MOTOR_R_IN1 = 21;
constexpr int PIN_MOTOR_R_IN2 = 14;

// ---- Sensors ------------------------------------------------------------------------------
constexpr int PIN_IR_OBSTACLE_L = 38;  // SD slot pin, has a board pull-up: fine for an input
constexpr int PIN_IR_OBSTACLE_R = 2;
constexpr int PIN_IR_FLAME_L = 46;     // strapping pin: input only, check that the board still boots
constexpr int PIN_IR_FLAME_R = -1;     // no free pin left for a second flame sensor
constexpr int PIN_DHT = -1;            // no free pin left; the DHT11 only reads room temperature

// Pack voltage: 2S pack positive -> 100k -> this pin -> 33k -> GND (see docs/power.md).
// GPIO 1 is on ADC1, which keeps working while Wi-Fi is on (ADC2 does not).
constexpr int PIN_BATT_ADC = 1;
