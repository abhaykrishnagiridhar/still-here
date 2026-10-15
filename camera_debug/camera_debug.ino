// ESP32-CAM sensor probe. Reads the camera's ID over its I2C bus, so it works
// even when the camera driver refuses to start.
// Board: AI Thinker ESP32-CAM. Serial Monitor: 115200 baud. Arduino-ESP32 core 3.x.
#include <Wire.h>

const int PIN_PWDN = 32;  // camera power-down, LOW = camera on
const int PIN_XCLK = 0;   // camera clock
const int PIN_SDA  = 26;
const int PIN_SCL  = 27;

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
  if (value < 0) Serial.printf("    %-30s no answer\n", label);
  else Serial.printf("    %-30s 0x%02X\n", label, value);
}

void probe(uint8_t addr) {
  Serial.printf("  Device answered at 0x%02X\n", addr);
  writeReg8(addr, 0xFF, 0x01);  // OV2640 keeps its ID in register bank 1
  show("reg 0x0A (OV2640 ID high)", readReg(addr, 0x0A, 1));
  show("reg 0x0B (OV2640 ID low)", readReg(addr, 0x0B, 1));
  show("reg 0x300A (OV3660/5640 hi)", readReg(addr, 0x300A, 2));
  show("reg 0x300B (OV3660/5640 lo)", readReg(addr, 0x300B, 2));
  show("reg 0xF0 (GC chip id high)", readReg(addr, 0xF0, 1));
  show("reg 0xF1 (GC chip id low)", readReg(addr, 0xF1, 1));
}

void setup() {
  Serial.begin(115200);
  delay(1500);
  Serial.println("\n=== ESP32-CAM sensor probe ===");

  pinMode(PIN_PWDN, OUTPUT);
  digitalWrite(PIN_PWDN, LOW);        // power the camera
  ledcAttach(PIN_XCLK, 20000000, 2);  // 20 MHz camera clock
  ledcWrite(PIN_XCLK, 2);             // 50 percent duty
  delay(200);

  Wire.begin(PIN_SDA, PIN_SCL, 100000);

  int found = 0;
  Serial.println("I2C devices that answered:");
  for (uint8_t a = 0x08; a < 0x78; a++) {
    Wire.beginTransmission(a);
    if (Wire.endTransmission() == 0) {
      probe(a);
      found++;
    }
  }
  if (found == 0) Serial.println("  none. The camera is not answering: check its power, ribbon and latch.");
  Serial.println("=== done ===");
}

void loop() { delay(1000); }
