#include <Adafruit_PWMServoDriver.h>
#include <Arduino.h>
#include <DHT.h>
#include <WebSocketsServer.h>
#include <WiFi.h>

#include "pins.h"

// Placeholder. Person C builds the camera stream, WebSocket server, arm and sensors here,
// following docs/protocol.md.

void setup() {
  Serial.begin(115200);
  Serial.println("STILL HERE firmware boot");
}

void loop() {
  delay(1000);
}
