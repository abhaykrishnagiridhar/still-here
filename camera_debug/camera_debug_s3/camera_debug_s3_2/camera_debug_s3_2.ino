// Full pin scan for the camera on an ESP32-S3 board whose pin map is unknown.
// Reference sketch, not built by PlatformIO: paste it into the Arduino IDE (File, New).
// Use it when cam_probe.txt says "none of the known maps".
//
// What it does, in three parts:
//   1. Pull-up check. Reads every usable pin with the chip's weak pull-down switched on. A pin that
//      still reads HIGH has a real pull-up resistor on the board: the camera bus (and the SD slot)
//      normally show up here. A camera that is plugged in and powered changes this list.
//   2. Scan. Tries every pair of pins as the camera's two-wire control bus. The 20 MHz camera clock
//      is sent to ALL the other pins at once, so the real clock pin is hit without trying each one
//      alone. Then the same again with one extra pin held LOW, and then HIGH, in case the camera
//      has a power-down or reset pin that must be set first.
//   3. Narrow down. On a hit it reads the sensor ID and tests the clock pins one at a time.
//
// It takes about 5 minutes. It never touches the flash, PSRAM or USB pins. The report repeats every
// 5 seconds at the end, so you cannot miss it. Send me the whole "SCAN RESULT" block.
//
// Arduino IDE settings (Tools menu): same as cam_probe.txt.
//   Board "ESP32S3 Dev Module", PSRAM "OPI PSRAM", Flash Size "16MB",
//   USB CDC On Boot "Enabled", USB Mode "Hardware CDC and JTAG". Serial Monitor at 115200 baud.
// Save the sketch under a plain name such as cam_scan. Do not touch the board while it runs.
#include <Arduino.h>
#include <Wire.h>
#include "driver/ledc.h"
#include "esp_rom_gpio.h"
#include "soc/gpio_sig_map.h"

// Every pin that could carry the camera. Left out on purpose: 0 (BOOT button), 19 and 20 (USB),
// 26 to 37 (flash and PSRAM), 43 and 44 (the USB-UART bridge).
const int CAND[] = {1,  2,  3,  4,  5,  6,  7,  8,  9,  10, 11, 12, 13, 14,
                    15, 16, 17, 18, 21, 38, 39, 40, 41, 42, 45, 46, 47, 48};
const int N = sizeof(CAND) / sizeof(CAND[0]);

// 7-bit I2C addresses the usual camera sensors answer on (OV7670, OV2640, OV3660/5640/GC, OV5640 alt).
const uint8_t ADDRS[] = {0x21, 0x30, 0x3C, 0x3D};
const int NOT_HELD = -1;
const int CLOCK_ALL = -1;

String g_report;  // the final answer, repeated by loop()

bool startClock() {
  // 20 MHz needs a 1-bit counter on the S3, the same setting the camera driver uses.
  ledc_timer_config_t timer = {};
  timer.speed_mode = LEDC_LOW_SPEED_MODE;
  timer.duty_resolution = LEDC_TIMER_1_BIT;
  timer.timer_num = LEDC_TIMER_0;
  timer.freq_hz = 20000000;
  timer.clk_cfg = LEDC_AUTO_CLK;
  if (ledc_timer_config(&timer) != ESP_OK) return false;

  ledc_channel_config_t ch = {};
  ch.gpio_num = 21;  // any pin; it is re-routed below
  ch.speed_mode = LEDC_LOW_SPEED_MODE;
  ch.channel = LEDC_CHANNEL_0;
  ch.timer_sel = LEDC_TIMER_0;
  ch.duty = 1;  // 50 percent
  ch.intr_type = LEDC_INTR_DISABLE;
  return ledc_channel_config(&ch) == ESP_OK;
}

// Sends the clock to one pin (clockPin) or to every pin that is free (CLOCK_ALL). The two bus pins
// become inputs, and the held pin is driven to heldLevel.
void route(int sda, int scl, int held, int heldLevel, int clockPin) {
  for (int i = 0; i < N; i++) {
    int p = CAND[i];
    esp_rom_gpio_connect_out_signal(p, SIG_GPIO_OUT_IDX, false, false);  // back to a plain pin
    if (p == sda || p == scl) {
      pinMode(p, INPUT);
    } else if (p == held) {
      pinMode(p, OUTPUT);
      digitalWrite(p, heldLevel);
    } else if (clockPin == CLOCK_ALL || clockPin == p) {
      pinMode(p, OUTPUT);
      esp_rom_gpio_connect_out_signal(p, LEDC_LS_SIG_OUT0_IDX + LEDC_CHANNEL_0, false, false);
    } else {
      pinMode(p, INPUT);
    }
  }
}

// Returns the first camera address that answers on this pin pair, or 0.
uint8_t answeringAddress(int sda, int scl) {
  if (!Wire.begin(sda, scl, 100000)) return 0;
  Wire.setTimeOut(5);
  uint8_t found = 0;
  for (uint8_t a : ADDRS) {
    Wire.beginTransmission(a);
    if (Wire.endTransmission() == 0) {
      found = a;
      break;
    }
  }
  Wire.end();
  return found;
}

struct Hit {
  int sda;
  int scl;
  int held;
  int heldLevel;
  uint8_t addr;
};

bool scanOnce(int held, int heldLevel, Hit& hit) {
  for (int i = 0; i < N; i++) {
    for (int j = 0; j < N; j++) {
      int sda = CAND[i], scl = CAND[j];
      if (i == j || sda == held || scl == held) continue;
      route(sda, scl, held, heldLevel, CLOCK_ALL);
      delay(1);
      uint8_t addr = answeringAddress(sda, scl);
      if (addr != 0) {
        hit = {sda, scl, held, heldLevel, addr};
        return true;
      }
    }
  }
  return false;
}

// Part 2: no held pin, then each pin held LOW, then each pin held HIGH.
bool scanAll(Hit& hit) {
  Serial.println("Scan 1 of 3: no pin held ...");
  if (scanOnce(NOT_HELD, LOW, hit)) return true;
  for (int level = LOW; level <= HIGH; level++) {
    Serial.printf("Scan %d of 3: one pin at a time held %s ...\n", level + 2, level ? "HIGH" : "LOW");
    for (int i = 0; i < N; i++) {
      Serial.printf("  holding GPIO%d\n", CAND[i]);
      if (scanOnce(CAND[i], level, hit)) return true;
    }
  }
  return false;
}

// Part 1: which pins have a real pull-up resistor on the board.
void pullUpCheck() {
  Serial.println("Part 1: pins that have a pull-up resistor on the board:");
  String high, low;
  for (int i = 0; i < N; i++) {
    pinMode(CAND[i], INPUT_PULLDOWN);
    delay(2);
    bool up = digitalRead(CAND[i]) == HIGH;
    pinMode(CAND[i], INPUT_PULLUP);
    delay(2);
    bool down = digitalRead(CAND[i]) == LOW;
    if (up) high += String(CAND[i]) + " ";
    if (down) low += String(CAND[i]) + " ";
    pinMode(CAND[i], INPUT);
  }
  Serial.printf("  pulled HIGH (pull-up resistor): %s\n", high.length() ? high.c_str() : "none");
  Serial.printf("  pulled LOW  (pull-down or driven low): %s\n", low.length() ? low.c_str() : "none");
}

int readReg(uint8_t addr, uint16_t reg, int regBytes) {
  Wire.beginTransmission(addr);
  if (regBytes == 2) Wire.write((uint8_t)(reg >> 8));
  Wire.write((uint8_t)(reg & 0xFF));
  if (Wire.endTransmission() != 0) return -1;
  if (Wire.requestFrom((int)addr, 1) != 1) return -1;
  return Wire.read();
}

void addIdLine(const char* label, int value) {
  char line[64];
  if (value < 0) snprintf(line, sizeof(line), "    %-28s no answer\n", label);
  else snprintf(line, sizeof(line), "    %-28s 0x%02X\n", label, value);
  g_report += line;
}

// Part 3: read the sensor ID, then find which single pins make the camera answer.
void narrowDown(const Hit& hit) {
  char head[160];
  snprintf(head, sizeof(head), "A camera device answered.\n  SDA=GPIO%d  SCL=GPIO%d  address 0x%02X\n",
           hit.sda, hit.scl, hit.addr);
  g_report += head;
  if (hit.held == NOT_HELD) {
    g_report += "  no pin needed to be held\n";
  } else {
    snprintf(head, sizeof(head), "  GPIO%d had to be held %s (the camera's power-down or reset pin)\n",
             hit.held, hit.heldLevel ? "HIGH" : "LOW");
    g_report += head;
  }

  g_report += "  clock pin candidates (the camera answers with the clock on only this pin):";
  int firstClock = -1;
  for (int i = 0; i < N; i++) {
    int x = CAND[i];
    if (x == hit.sda || x == hit.scl || x == hit.held) continue;
    route(hit.sda, hit.scl, hit.held, hit.heldLevel, x);
    delay(5);
    if (answeringAddress(hit.sda, hit.scl) != 0) {
      g_report += " GPIO" + String(x);
      if (firstClock < 0) firstClock = x;
    }
  }
  g_report += firstClock < 0 ? " none (only works with the clock on several pins)\n" : "\n";

  route(hit.sda, hit.scl, hit.held, hit.heldLevel, firstClock);
  delay(5);
  if (!Wire.begin(hit.sda, hit.scl, 100000)) return;
  Wire.setTimeOut(5);
  g_report += "  sensor ID registers:\n";
  Wire.beginTransmission(hit.addr);
  Wire.write(0xFF);  // OV2640 keeps its ID in register bank 1
  Wire.write(0x01);
  Wire.endTransmission();
  addIdLine("0x0A (OV2640 ID high)", readReg(hit.addr, 0x0A, 1));
  addIdLine("0x0B (OV2640 ID low)", readReg(hit.addr, 0x0B, 1));
  addIdLine("0x300A (OV3660/5640 high)", readReg(hit.addr, 0x300A, 2));
  addIdLine("0x300B (OV3660/5640 low)", readReg(hit.addr, 0x300B, 2));
  addIdLine("0xF0 (GC chip id high)", readReg(hit.addr, 0xF0, 1));
  addIdLine("0xF1 (GC chip id low)", readReg(hit.addr, 0xF1, 1));
  Wire.end();
}

void setup() {
  Serial.begin(115200);
  // Over the native USB port the Serial Monitor can only attach after the board restarts.
  unsigned long start = millis();
  while (!Serial && millis() - start < 10000) delay(10);
  delay(500);

  Serial.println("\n=== ESP32-S3 camera pin scan, about 5 minutes ===");
  pullUpCheck();
  if (!startClock()) {
    g_report = "The 20 MHz clock could not be started, so the scan cannot run.\n";
    return;
  }
  Hit hit;
  if (scanAll(hit)) {
    narrowDown(hit);
  } else {
    g_report =
        "No camera answered on any pin pair, with or without a held pin.\n"
        "  Most likely: the ribbon is not fully in (latch closed, contacts facing the right way),\n"
        "  the camera module is dead, or its power switch or jumper is off. Reseat it and run again.\n";
  }
}

void loop() {
  Serial.println("\n=== SCAN RESULT ===");
  Serial.print(g_report);
  Serial.println("How to read the ID:");
  Serial.println("  address 0x30, ID 0x26 then 0x42/0x41 -> OV2640 (what the project wants)");
  Serial.println("  address 0x3C, ID 0x36/0x60           -> OV3660");
  Serial.println("  address 0x3C, ID 0x56/0x40           -> OV5640");
  Serial.println("  address 0x3C, GC regs 0x21/0x45      -> GC2145 (no JPEG output, avoid)");
  Serial.println("=== end of result, repeating in 5 seconds ===");
  delay(5000);
}
