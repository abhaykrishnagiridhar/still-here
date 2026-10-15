#include <Adafruit_PWMServoDriver.h>
#include <Arduino.h>
#include <DHT.h>
#include <WebSocketsServer.h>
#include <WiFi.h>

#include "camera.h"
#include "mjpeg_server.h"
#include "pins.h"

#if __has_include("secrets.h")
#include "secrets.h"
#else
#error "Copy firmware/secrets.example.h to firmware/secrets.h and fill in your Wi-Fi name and password."
#endif

// Person C builds the WebSocket server, arm and sensors here next, following docs/protocol.md.
// For now: join the Wi-Fi, start the camera and serve the video at http://<rover-ip>/stream.

constexpr uint32_t WIFI_JOIN_TIMEOUT_MS = 20000;
constexpr uint32_t STATUS_EVERY_MS = 5000;

bool joinWifi() {
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);  // Wi-Fi power saving makes video stutter
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  uint32_t start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < WIFI_JOIN_TIMEOUT_MS) {
    delay(250);
  }
  return WiFi.status() == WL_CONNECTED;
}

void setup() {
  Serial.begin(115200);
  delay(1500);  // the native USB serial port needs a moment before it shows anything
  Serial.println("STILL HERE firmware boot");

  if (joinWifi()) {
    Serial.printf("wifi: joined, rover address %s\n", WiFi.localIP().toString().c_str());
  } else {
    Serial.println("wifi: could not join. Is the hotspot on, set to 2.4 GHz, and secrets.h right?");
  }

  if (cameraBegin()) {
    mjpegServerBegin();
    Serial.printf("camera: video at http://%s/stream\n", WiFi.localIP().toString().c_str());
  }
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("wifi: lost, reconnecting");
    WiFi.reconnect();
  }
  Serial.printf("camera: %.1f fps, %u ms to make each JPEG, %d viewer(s)\n", cameraFramesPerSecond(),
                (unsigned)cameraEncodeMillis(), mjpegViewerCount());
  delay(STATUS_EVERY_MS);
}
