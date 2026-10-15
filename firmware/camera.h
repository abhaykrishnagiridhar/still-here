#pragma once

#include <Arduino.h>
#include <esp_camera.h>

// Camera on the S3 board, with the GC2145 sensor.
//
// The GC2145 cannot make JPEG pictures itself. So the camera gives raw RGB565 pictures into the
// PSRAM, and a background task turns each one into a JPEG with the chip's own CPU. The newest
// JPEG is kept in one place that any number of viewers can read, so the work is done once per
// picture however many people are watching.
//
// Change these to trade picture size against speed. Watch the "camera" line on the serial console,
// which prints the speed every 5 seconds.
// Measured on this board: FRAMESIZE_VGA (640x480) made 3.4 fps, too slow for the pulsing light.
// FRAMESIZE_CIF is 400x296, FRAMESIZE_QVGA is 320x240 (faster still).
constexpr framesize_t CAMERA_FRAME_SIZE = FRAMESIZE_CIF;
constexpr uint8_t CAMERA_JPEG_QUALITY = 80;               // 1 to 100, higher is sharper and bigger
constexpr bool CAMERA_VFLIP = false;                      // flip the picture upside down
constexpr bool CAMERA_HMIRROR = false;                    // mirror the picture left to right

// The camera's control bus uses I2C port 0 (the Arduino "Wire"). Anything else on I2C, such as the
// servo driver, must use Wire1.

// Starts the sensor and the background task. Returns false (and says why on Serial) if the sensor
// does not answer.
bool cameraBegin();

// Copies the newest JPEG into *buffer, growing it when needed. Waits up to timeoutMs for a picture
// newer than lastSeq. Returns true when it got one: then *length and *seq are filled in.
// Start with *buffer = nullptr and *capacity = 0, and free(*buffer) when done.
bool cameraWaitForFrame(uint32_t lastSeq, uint8_t** buffer, size_t* capacity, size_t* length,
                        uint32_t* seq, uint32_t timeoutMs);

float cameraFramesPerSecond();
uint32_t cameraEncodeMillis();  // average time to make one JPEG, over the last few seconds
