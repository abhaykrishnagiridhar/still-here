#include "camera.h"

#include <esp_heap_caps.h>
#include <img_converters.h>

#include "pins.h"

namespace {

constexpr uint32_t CAMERA_CLOCK_HZ = 20000000;
constexpr uint32_t STATS_WINDOW_MS = 5000;
constexpr uint32_t FAILED_GRAB_PAUSE_MS = 50;
constexpr uint32_t CAPTURE_TASK_STACK = 12288;
constexpr uint32_t POLL_MS = 4;
constexpr int CAPTURE_CORE = 1;  // Wi-Fi runs on core 0

SemaphoreHandle_t g_lock = nullptr;  // guards the values below
uint8_t* g_jpeg = nullptr;
size_t g_jpegCapacity = 0;
size_t g_jpegLength = 0;
uint32_t g_seq = 0;

volatile float g_fps = 0;
volatile uint32_t g_encodeMs = 0;

void* growPsram(void* old, size_t bytes) {
  return heap_caps_realloc(old, bytes, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
}

camera_config_t makeConfig() {
  camera_config_t config = {};
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;
  config.pin_d0 = CAM_PIN_D0;
  config.pin_d1 = CAM_PIN_D1;
  config.pin_d2 = CAM_PIN_D2;
  config.pin_d3 = CAM_PIN_D3;
  config.pin_d4 = CAM_PIN_D4;
  config.pin_d5 = CAM_PIN_D5;
  config.pin_d6 = CAM_PIN_D6;
  config.pin_d7 = CAM_PIN_D7;
  config.pin_xclk = CAM_PIN_XCLK;
  config.pin_pclk = CAM_PIN_PCLK;
  config.pin_vsync = CAM_PIN_VSYNC;
  config.pin_href = CAM_PIN_HREF;
  config.pin_sccb_sda = CAM_PIN_SIOD;
  config.pin_sccb_scl = CAM_PIN_SIOC;
  config.pin_pwdn = CAM_PIN_PWDN;
  config.pin_reset = CAM_PIN_RESET;
  config.xclk_freq_hz = CAMERA_CLOCK_HZ;
  config.pixel_format = PIXFORMAT_RGB565;  // the GC2145 has no JPEG output
  config.frame_size = CAMERA_FRAME_SIZE;
  config.jpeg_quality = 12;  // unused: the sensor does not make JPEG
  config.fb_count = 2;
  config.fb_location = CAMERA_FB_IN_PSRAM;
  config.grab_mode = CAMERA_GRAB_LATEST;  // always the newest picture, never a stale one
  return config;
}

// Stores a finished JPEG as the newest one. Returns false if there was no memory for it.
bool publish(const uint8_t* jpeg, size_t length) {
  xSemaphoreTake(g_lock, portMAX_DELAY);
  bool stored = true;
  if (length > g_jpegCapacity) {
    size_t wanted = length + length / 4;
    void* grown = growPsram(g_jpeg, wanted);
    if (grown) {
      g_jpeg = static_cast<uint8_t*>(grown);
      g_jpegCapacity = wanted;
    } else {
      stored = false;
    }
  }
  if (stored) {
    memcpy(g_jpeg, jpeg, length);
    g_jpegLength = length;
    g_seq++;
  }
  xSemaphoreGive(g_lock);
  return stored;
}

void captureTask(void*) {
  uint32_t windowStart = millis();
  uint32_t frames = 0;
  uint32_t encodeTotal = 0;
  for (;;) {
    camera_fb_t* picture = esp_camera_fb_get();
    if (!picture) {
      vTaskDelay(pdMS_TO_TICKS(FAILED_GRAB_PAUSE_MS));
      continue;
    }
    uint32_t encodeStart = millis();
    uint8_t* jpeg = nullptr;
    size_t jpegLength = 0;
    bool encoded = frame2jpg(picture, CAMERA_JPEG_QUALITY, &jpeg, &jpegLength);
    esp_camera_fb_return(picture);
    if (encoded) {
      encodeTotal += millis() - encodeStart;
      frames++;
      publish(jpeg, jpegLength);
      free(jpeg);
    }

    uint32_t now = millis();
    if (now - windowStart >= STATS_WINDOW_MS) {
      g_fps = frames * 1000.0f / (now - windowStart);
      g_encodeMs = frames ? encodeTotal / frames : 0;
      windowStart = now;
      frames = 0;
      encodeTotal = 0;
    }
    vTaskDelay(1);  // let the other tasks run
  }
}

void applySensorSettings() {
  sensor_t* sensor = esp_camera_sensor_get();
  if (!sensor) return;
  Serial.printf("camera: sensor PID 0x%04X (the GC2145 is 0x2145)\n", sensor->id.PID);
  sensor->set_vflip(sensor, CAMERA_VFLIP);
  sensor->set_hmirror(sensor, CAMERA_HMIRROR);
}

}  // namespace

bool cameraBegin() {
  g_lock = xSemaphoreCreateMutex();
  if (!psramFound()) {
    Serial.println("camera: no PSRAM found. In the board settings, PSRAM must be OPI.");
    return false;
  }
  camera_config_t config = makeConfig();
  esp_err_t error = esp_camera_init(&config);
  if (error != ESP_OK) {
    Serial.printf("camera: sensor did not start, error 0x%x. Check the ribbon and the camera.\n",
                  error);
    return false;
  }
  applySensorSettings();
  xTaskCreatePinnedToCore(captureTask, "camera", CAPTURE_TASK_STACK, nullptr, 2, nullptr,
                          CAPTURE_CORE);
  return true;
}

bool cameraWaitForFrame(uint32_t lastSeq, uint8_t** buffer, size_t* capacity, size_t* length,
                        uint32_t* seq, uint32_t timeoutMs) {
  uint32_t start = millis();
  while (millis() - start < timeoutMs) {
    xSemaphoreTake(g_lock, portMAX_DELAY);
    bool isNew = g_seq != lastSeq && g_jpegLength > 0;
    bool copied = false;
    if (isNew) {
      if (g_jpegLength > *capacity) {
        void* grown = growPsram(*buffer, g_jpegLength);
        if (grown) {
          *buffer = static_cast<uint8_t*>(grown);
          *capacity = g_jpegLength;
        }
      }
      if (g_jpegLength <= *capacity) {
        memcpy(*buffer, g_jpeg, g_jpegLength);
        *length = g_jpegLength;
        *seq = g_seq;
        copied = true;
      }
    }
    xSemaphoreGive(g_lock);
    if (copied) return true;
    vTaskDelay(pdMS_TO_TICKS(POLL_MS));
  }
  return false;
}

float cameraFramesPerSecond() {
  return g_fps;
}

uint32_t cameraEncodeMillis() {
  return g_encodeMs;
}
