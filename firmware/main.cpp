#include <Arduino.h>
#include <WiFi.h>

#include "camera.h"
#include "hardware.h"
#include "mjpeg_server.h"
#include "pins.h"
#include "rover_core.h"
#include "rover_link.h"

#if __has_include("secrets.h")
#include "secrets.h"
#else
#error "Copy firmware/secrets.example.h to firmware/secrets.h and fill in your Wi-Fi name and password."
#endif

// What runs on the rover:
//   - the camera, served as video at http://<rover-ip>/stream      (camera.cpp, mjpeg_server.cpp)
//   - the command link, ws://<rover-ip>:81/ and still-here.local    (rover_link.cpp)
//   - the behaviour: plans, link loss, safe stop, speed limits      (rover_core.h, tested on a PC)
//   - the real wheels, arm and sensors                               (hardware.cpp, NOT yet bench-tested)
// What is done and what is left is in docs/tasks.md, section C.

constexpr uint32_t WIFI_JOIN_TIMEOUT_MS = 20000;
constexpr uint32_t STATUS_EVERY_MS = 5000;

ArduinoRoverHardware g_hardware;
RoverCore g_core(g_hardware, roverLinkSink());

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
  roverPinsSafeState();  // first of all: the wheels must not move while everything else starts
  Serial.begin(115200);
  delay(1500);  // the native USB serial port needs a moment before it shows anything
  Serial.println("STILL HERE firmware boot");

  g_hardware.begin();
  g_core.begin(millis());
  g_core.setObstacleStop(IR_OBSTACLE_STOP_ENABLED);

  if (joinWifi()) {
    Serial.printf("wifi: joined, rover address %s\n", WiFi.localIP().toString().c_str());
  } else {
    Serial.println("wifi: could not join. Is the hotspot on, set to 2.4 GHz, and secrets.h right?");
  }

  if (cameraBegin()) {
    mjpegServerBegin();
    Serial.printf("camera: video at http://%s/stream\n", WiFi.localIP().toString().c_str());
  }

  roverLinkBegin(g_core);
}

void loop() {
  roverLinkLoop();
  g_core.tick(millis());

  static uint32_t lastStatus = 0;
  if (millis() - lastStatus >= STATUS_EVERY_MS) {
    lastStatus = millis();
    if (WiFi.status() != WL_CONNECTED) {
      Serial.println("wifi: lost, reconnecting");
      WiFi.reconnect();
    }
    Serial.printf("camera: %.1f fps, %u ms per JPEG, %d viewer(s) | link: %s, operator %s\n", cameraFramesPerSecond(),
                  (unsigned)cameraEncodeMillis(), mjpegViewerCount(), g_core.linkUp() ? "up" : "down",
                  roverLinkHasOperator() ? "connected" : "none");
  }
  delay(2);  // the core ticks about 400 times a second, far more than it needs
}
