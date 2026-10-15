#include <Arduino.h>
#include <WiFi.h>
#include <esp_system.h>
#include <stdarg.h>

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

// Start-up can be cut short to find a problem: build with -DBOOT_STAGE=n (platformio.ini build_flags).
//   0 = serial only        1 = + wheel, servo and sensor pins        2 = + Wi-Fi
//   3 = + camera           4 = everything (the default)
#ifndef BOOT_STAGE
#define BOOT_STAGE 4
#endif

constexpr uint32_t WIFI_JOIN_TIMEOUT_MS = 20000;
constexpr uint32_t STATUS_EVERY_MS = 5000;

// The command link and the rover's behaviour run in their own task, at a HIGHER priority than the
// camera's (camera.cpp uses 2), on the same core. Encoding a picture takes about 100 ms, so without
// this the link got only the gaps between pictures: messages were lost and the safety timers ran late.
// These two jobs need almost no time, so they can always interrupt the camera. Everything that touches
// g_core, the link or the hardware happens in this one task.
constexpr int CONTROL_TASK_PRIORITY = 3;
constexpr int CONTROL_CORE = 1;
constexpr uint32_t CONTROL_TASK_STACK = 8192;
constexpr uint32_t CONTROL_PERIOD_MS = 5;

ArduinoRoverHardware g_hardware;
RoverCore g_core(g_hardware, roverLinkSink());

static void controlTask(void*) {
  for (;;) {
    if (BOOT_STAGE >= 4) roverLinkLoop();
    g_core.tick(millis());
    vTaskDelay(pdMS_TO_TICKS(CONTROL_PERIOD_MS));
  }
}

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

// Prints on the native USB port and on the UART port, so the line is seen whichever one is open.
static void say(const char* format, ...) {
  char line[200];
  va_list args;
  va_start(args, format);
  vsnprintf(line, sizeof line, format, args);
  va_end(args);
  Serial.println(line);
#if ARDUINO_USB_CDC_ON_BOOT
  Serial0.println(line);  // the UART port too, so the line is seen on either
#endif
}

static const char* resetName(esp_reset_reason_t reason) {
  switch (reason) {
    case ESP_RST_POWERON: return "POWERON";
    case ESP_RST_SW: return "SW restart";
    case ESP_RST_PANIC: return "PANIC (crash)";
    case ESP_RST_INT_WDT: return "INT_WDT";
    case ESP_RST_TASK_WDT: return "TASK_WDT";
    case ESP_RST_WDT: return "WDT";
    case ESP_RST_BROWNOUT: return "BROWNOUT (supply sagged)";
    default: return "other";
  }
}

void setup() {
  roverPinsSafeState();  // first of all: the wheels must not move while everything else starts
  Serial.begin(115200);
#if ARDUINO_USB_CDC_ON_BOOT
  Serial0.begin(115200);
#endif
  delay(1500);  // the native USB serial port needs a moment before it shows anything
  say("STILL HERE firmware boot (stage %d of 4)", BOOT_STAGE);
  say("started because: %s | psram %u bytes | free heap %u bytes", resetName(esp_reset_reason()),
      static_cast<unsigned>(ESP.getPsramSize()), static_cast<unsigned>(ESP.getFreeHeap()));

  if (BOOT_STAGE >= 1) {
    g_hardware.begin();
    g_core.begin(millis());
    g_core.setObstacleStop(IR_OBSTACLE_STOP_ENABLED);
    say("pins: wheels, servos and sensors set up");
  }

  if (BOOT_STAGE >= 2) {
    if (joinWifi()) {
      say("wifi: joined, rover address %s", WiFi.localIP().toString().c_str());
    } else {
      say("wifi: could not join. Is the hotspot on, set to 2.4 GHz, and secrets.h right?");
    }
  }

  if (BOOT_STAGE >= 3 && cameraBegin()) {
    mjpegServerBegin();
    say("camera: video at http://%s/stream", WiFi.localIP().toString().c_str());
  }

  if (BOOT_STAGE >= 4) roverLinkBegin(g_core);
  if (BOOT_STAGE >= 1) {
    xTaskCreatePinnedToCore(controlTask, "control", CONTROL_TASK_STACK, nullptr, CONTROL_TASK_PRIORITY, nullptr, CONTROL_CORE);
  }
}

void loop() {
  static uint32_t lastStatus = 0;
  const uint32_t every = BOOT_STAGE >= 3 ? STATUS_EVERY_MS : 1000;
  if (millis() - lastStatus >= every) {
    lastStatus = millis();
    if (BOOT_STAGE >= 2 && WiFi.status() != WL_CONNECTED) {
      Serial.println("wifi: lost, reconnecting");
      WiFi.reconnect();
    }
    if (BOOT_STAGE >= 3) {
      Serial.printf("camera: %.1f fps, %u ms per JPEG, %d viewer(s) | link: %s, operator %s\n", cameraFramesPerSecond(),
                    (unsigned)cameraEncodeMillis(), mjpegViewerCount(), g_core.linkUp() ? "up" : "down",
                    roverLinkHasOperator() ? "connected" : "none");
    } else {
      say("alive, %lu s since start", static_cast<unsigned long>(millis() / 1000));
    }
  }
  delay(50);  // this loop only prints the status line now; the control task does the real work
}
