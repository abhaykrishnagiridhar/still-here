#include <Arduino.h>

// Placeholder for the ESP32-CAM, so the toolchain can be checked end to end.
// The camera streaming firmware (cam_stream.cpp) replaces this later.

void setup() {
  Serial.begin(115200);
  Serial.println("STILL HERE camera boot");
}

void loop() {
  delay(1000);
}
