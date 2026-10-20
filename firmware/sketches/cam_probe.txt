// Camera sensor probe for an ESP32-S3 board with a built-in camera socket.
// Reference sketch, not built by PlatformIO: paste it into the Arduino IDE (File, New).
//
// What it does: for each well-known ESP32-S3 camera pin map, it starts the camera clock on that
// map's clock pin, then scans the camera's own I2C bus on that map's two pins and reads the
// sensor's ID registers. It works even when the camera driver refuses to start. The report
// repeats every 5 seconds, so you cannot miss it.
//
// Result: the line "MAP THAT WORKED" names the right pins. Copy them into firmware/pins.h
// (the CAM_PIN_XCLK, CAM_PIN_SIOD and CAM_PIN_SIOC lines).
//
// Arduino IDE settings (Tools menu):
//   Board "ESP32S3 Dev Module", PSRAM "OPI PSRAM", Flash Size "16MB"
//   USB CDC On Boot "Enabled"   <- needed to see Serial on the native USB-C port
//   USB Mode "Hardware CDC and JTAG"
// Save the sketch under a plain name such as cam_probe (letters, numbers, underscores only).
// Serial Monitor: 115200 baud. Needs Arduino-ESP32 core 3.x. Not tested on this board yet.
//
// If the Serial Monitor stays empty: close and reopen it after the board restarts (the USB
// port drops and returns on every reset), or plug into the OTHER USB-C port and set
// "USB CDC On Boot" to "Disabled".
#include <Wire.h>

struct CamMap {
  const char* name;
  int xclk;  // camera clock
  int sda;   // camera control bus
  int scl;
  int pwdn;  // -1 means not wired
};

const CamMap MAPS[] = {
    {"ESP32-S3-EYE style (Freenove and many clones)", 15, 4, 5, -1},
    {"LilyGO T-Camera S3", 14, 4, 5, -1},
    {"ESP32-S3 CAM LCD board", 40, 17, 18, -1},
    {"XIAO ESP32S3 Sense", 10, 40, 39, -1},
    {"FireBeetle 2 / Romeo ESP32-S3", 45, 1, 2, -1},
    {"M5Stack CamS3", 11, 17, 41, -1},
};
const int MAP_COUNT = sizeof(MAPS) / sizeof(MAPS[0]);

bool writeReg8(uint8_t addr, uint8_t reg, uint8_t value) {
  Wire.beginTransmission(addr);
  Wire.write(reg);
  Wire.write(value);
  return Wire.endTransmission() == 0;
}

// Reads one byte. regBytes is 1 (8-bit register address) or 2 (16-bit).
int readReg(uint8_t addr, uint16_t reg, int regBytes) {
  Wire.beginTransmission(addr);
  if (regBytes == 2) Wire.write((uint8_t)(reg >> 8));
  Wire.write((uint8_t)(reg & 0xFF));
  if (Wire.endTransmission() != 0) return -1;
  if (Wire.requestFrom((uint16_t)addr, (size_t)1) != 1) return -1;
  return Wire.read();
}

void show(const char* label, int value) {
  if (value < 0) Serial.printf("      %-30s no answer\n", label);
  else Serial.printf("      %-30s 0x%02X\n", label, value);
}

void probe(uint8_t addr) {
  Serial.printf("    Device answered at 0x%02X\n", addr);
  writeReg8(addr, 0xFF, 0x01);  // OV2640 keeps its ID in register bank 1
  show("reg 0x0A (OV2640 ID high)", readReg(addr, 0x0A, 1));
  show("reg 0x0B (OV2640 ID low)", readReg(addr, 0x0B, 1));
  show("reg 0x300A (OV3660/5640 hi)", readReg(addr, 0x300A, 2));
  show("reg 0x300B (OV3660/5640 lo)", readReg(addr, 0x300B, 2));
  show("reg 0xF0 (GC chip id high)", readReg(addr, 0xF0, 1));
  show("reg 0xF1 (GC chip id low)", readReg(addr, 0xF1, 1));
}

// Tries one pin map. Returns how many I2C devices answered.
int tryMap(const CamMap& m) {
  if (m.pwdn >= 0) {
    pinMode(m.pwdn, OUTPUT);
    digitalWrite(m.pwdn, LOW);  // power the camera
  }
  // 20 MHz needs a 1-bit counter on the S3, the same setting the camera driver uses. A 2-bit
  // counter at 20 MHz is out of the chip's reach, and the clock then silently never starts.
  bool clockOk = ledcAttach(m.xclk, 20000000, 1);
  if (clockOk) ledcWrite(m.xclk, 1);  // 50 percent duty
  delay(40);

  bool busOk = Wire.begin(m.sda, m.scl, 100000);
  if (busOk) Wire.setTimeOut(5);  // give up quickly on a bus that does not answer
  Serial.printf("  %s\n    XCLK=%d SDA=%d SCL=%d | clock started: %s | I2C started: %s\n", m.name,
                m.xclk, m.sda, m.scl, clockOk ? "yes" : "NO", busOk ? "yes" : "NO");

  int found = 0;
  if (busOk) {
    for (uint8_t a = 0x08; a < 0x78; a++) {
      Wire.beginTransmission(a);
      if (Wire.endTransmission() == 0) {
        probe(a);
        found++;
      }
    }
  }
  if (found == 0) Serial.println("    nothing answered");

  // Let go of the pins, so the next map starts clean.
  Wire.end();
  if (clockOk) ledcDetach(m.xclk);
  pinMode(m.xclk, INPUT);
  pinMode(m.sda, INPUT);
  pinMode(m.scl, INPUT);
  return found;
}

void runProbe() {
  Serial.printf("\n=== ESP32-S3 camera probe, running for %lu s ===\n", millis() / 1000);
  int worked = -1;
  for (int i = 0; i < MAP_COUNT; i++) {
    if (tryMap(MAPS[i]) > 0 && worked < 0) worked = i;
  }
  if (worked >= 0) {
    Serial.printf("MAP THAT WORKED: %s  (XCLK=%d SDA=%d SCL=%d)\n", MAPS[worked].name,
                  MAPS[worked].xclk, MAPS[worked].sda, MAPS[worked].scl);
  } else {
    Serial.println("MAP THAT WORKED: none of the known maps.");
    Serial.println("  Check the ribbon (fully in, latch closed, right socket), then tell me the");
    Serial.println("  board's product name, or ask for the full pin scan.");
  }
  Serial.println("How to read the ID:");
  Serial.println("  0x30 with ID 0x26 and 0x42/0x41  -> OV2640 (what the project wants)");
  Serial.println("  0x3C with ID 0x36/0x60           -> OV3660");
  Serial.println("  0x3C with ID 0x56/0x40           -> OV5640");
  Serial.println("  0x3C with ID 0x21/0x45 (GC regs) -> GC2145 (no JPEG output, avoid)");
  Serial.println("=== end of report, repeating in 5 seconds ===");
}

void setup() {
  Serial.begin(115200);
  // Over the native USB port the Serial Monitor can only attach after the board restarts.
  // Wait up to 10 seconds for it, then keep repeating the report from loop().
  unsigned long start = millis();
  while (!Serial && millis() - start < 10000) delay(10);
  delay(500);
}

void loop() {
  runProbe();
  delay(5000);
}
