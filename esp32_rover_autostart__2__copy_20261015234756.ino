#include <Arduino.h>
#include <BluetoothSerial.h>

#if !defined(CONFIG_BT_ENABLED) || !defined(CONFIG_BLUEDROID_ENABLED)
#error "Classic Bluetooth is not enabled. Use an original ESP32 board (not S2/S3/C3)."
#endif

BluetoothSerial SerialBT;

const char* BT_NAME = "ESP32_ROVER";

// ---------- Auto-start settings ----------
const bool AUTO_START = false;                // true = move on power-up, false = stay still until a command
const unsigned long AUTO_START_DELAY_MS = 3000; // wait before moving (time to put rover on ground)
const unsigned long AUTO_RUN_TIME_MS = 0;     // 0 = run until a Bluetooth command, else stop after this time

// L298N pins
const int ENA = 25;
const int IN1 = 26;
const int IN2 = 27;
const int IN3 = 13;
const int IN4 = 32;
const int ENB = 33;

// PWM
const int PWM_FREQ = 1000;
const int PWM_BITS = 8;

// Tilt safety timeout (only used while in TILT mode)
const unsigned long TILT_TIMEOUT_MS = 700;

// Tilt tuning
const float TILT_DEADZONE = 8.0;
const float TILT_GAIN = 3.0;

int driveSpeed = 170;          // changed by '0'-'9' and 'q'
unsigned long lastTilt = 0;
bool tiltActive = false;

// Auto-run state
bool autoRunning = false;
unsigned long autoStartedAt = 0;

String rxLine;
unsigned long lastRx = 0;

// ---------- PWM helper (works on Core 2.x and 3.x) ----------
void pwmSetup() {
#if ESP_ARDUINO_VERSION_MAJOR >= 3
  ledcAttach(ENA, PWM_FREQ, PWM_BITS);
  ledcAttach(ENB, PWM_FREQ, PWM_BITS);
#else
  ledcSetup(0, PWM_FREQ, PWM_BITS);
  ledcSetup(1, PWM_FREQ, PWM_BITS);
  ledcAttachPin(ENA, 0);
  ledcAttachPin(ENB, 1);
#endif
}

void pwmWrite(int pin, int duty) {
#if ESP_ARDUINO_VERSION_MAJOR >= 3
  ledcWrite(pin, duty);
#else
  ledcWrite(pin == ENA ? 0 : 1, duty);
#endif
}

// ---------- Motor control ----------
void setMotor(int en, int a, int b, int speed) {
  speed = constrain(speed, -255, 255);

  if (speed > 0) {
    digitalWrite(a, HIGH);
    digitalWrite(b, LOW);
  } else if (speed < 0) {
    digitalWrite(a, LOW);
    digitalWrite(b, HIGH);
  } else {
    digitalWrite(a, LOW);
    digitalWrite(b, LOW);
  }
  pwmWrite(en, abs(speed));
}

void drive(int left, int right) {
  setMotor(ENA, IN1, IN2, left);
  setMotor(ENB, IN3, IN4, right);
}

void mixDrive(float throttle, float steering) {
  int left  = round(throttle + steering);
  int right = round(throttle - steering);

  int largest = max(abs(left), abs(right));
  if (largest > 255) {
    left  = left * 255 / largest;
    right = right * 255 / largest;
  }
  drive(left, right);
}

// ---------- Tilt control: "TILT:pitch,roll" + newline ----------
void handleTilt(String data) {
  int comma = data.indexOf(',');
  if (comma < 0) return;

  float pitch = data.substring(0, comma).toFloat();
  float roll  = data.substring(comma + 1).toFloat();

  if (abs(pitch) > 90 || abs(roll) > 90) {
    drive(0, 0);
    return;
  }

  float throttle = 0, steering = 0;
  if (abs(pitch) >= TILT_DEADZONE) throttle = constrain(pitch * TILT_GAIN, -255, 255);
  if (abs(roll)  >= TILT_DEADZONE) steering = constrain(roll * TILT_GAIN, -200, 200);

  autoRunning = false;
  tiltActive = true;
  lastTilt = millis();
  mixDrive(throttle, steering);
}

// ---------- Single-character commands (Arduino Bluetooth Controller) ----------
void handleChar(char c) {
  int turn  = driveSpeed * 9 / 10;
  int inner = driveSpeed * 4 / 10;

  // Ignore characters that are not real commands, so the auto-run isn't cancelled by noise
  bool valid = false;
  const char* cmds = "FBLRQGEIZHCJSD0123456789q";
  for (const char* p = cmds; *p; p++) {
    if (*p == c) { valid = true; break; }
  }
  if (!valid) return;

  // Any real command cancels auto-run and tilt mode
  autoRunning = false;
  tiltActive = false;

  switch (c) {
    case 'F': drive(driveSpeed, driveSpeed); break;
    case 'B': drive(-driveSpeed, -driveSpeed); break;
    case 'L': drive(-turn, turn); break;
    case 'R': drive(turn, -turn); break;

    case 'Q': case 'G': drive(inner, driveSpeed); break;    // forward-left
    case 'E': case 'I': drive(driveSpeed, inner); break;    // forward-right
    case 'Z': case 'H': drive(-inner, -driveSpeed); break;  // reverse-left
    case 'C': case 'J': drive(-driveSpeed, -inner); break;  // reverse-right

    case 'S': case 'D': drive(0, 0); break;                 // stop

    case '0': case '1': case '2': case '3': case '4':
    case '5': case '6': case '7': case '8': case '9':
      driveSpeed = 100 + (c - '0') * 17;                    // 100..253
      break;
    case 'q': driveSpeed = 255; break;

    default: break;
  }
}

void handleLine(String line) {
  line.trim();
  if (line.startsWith("TILT:")) {
    handleTilt(line.substring(5));
  } else if (line.length() == 1) {
    handleChar(line[0]);
  }
}

void setup() {
  // Force every motor pin LOW immediately so nothing can move during startup
  pinMode(IN1, OUTPUT);  digitalWrite(IN1, LOW);
  pinMode(IN2, OUTPUT);  digitalWrite(IN2, LOW);
  pinMode(IN3, OUTPUT);  digitalWrite(IN3, LOW);
  pinMode(IN4, OUTPUT);  digitalWrite(IN4, LOW);
  pinMode(ENA, OUTPUT);  digitalWrite(ENA, LOW);
  pinMode(ENB, OUTPUT);  digitalWrite(ENB, LOW);

  Serial.begin(115200);

  pwmSetup();
  drive(0, 0);

  if (!SerialBT.begin(BT_NAME)) {
    Serial.println("Bluetooth failed to start!");
    while (true) {
      drive(0, 0);
      delay(100);
    }
  }

  Serial.print("ESP32 Rover ready. Bluetooth name: ");
  Serial.println(BT_NAME);

  if (AUTO_START) {
    Serial.println("Auto-start enabled");
    delay(AUTO_START_DELAY_MS);
    drive(driveSpeed, driveSpeed);   // move forward on power-up
    autoRunning = true;
    autoStartedAt = millis();
  }
}

void loop() {
  while (SerialBT.available()) {
    char ch = SerialBT.read();
    lastRx = millis();

    if (ch == '\n' || ch == '\r') {
      if (rxLine.length() > 0) {
        handleLine(rxLine);
        rxLine = "";
      }
    } else if (rxLine.length() == 0 && ch != 'T') {
      // Normal single-character command, no newline needed
      handleChar(ch);
    } else {
      // Start/continue buffering a "TILT:..." line
      rxLine += ch;
      if (rxLine.length() > 40) rxLine = "";
    }
  }

  // Drop half-received garbage
  if (rxLine.length() > 0 && millis() - lastRx > 300) rxLine = "";

  // Auto-run: stop after the set time (if one is set)
  if (autoRunning && AUTO_RUN_TIME_MS > 0 && millis() - autoStartedAt > AUTO_RUN_TIME_MS) {
    autoRunning = false;
    drive(0, 0);
  }

  // Tilt mode: stop if tilt data stops arriving
  if (tiltActive && millis() - lastTilt > TILT_TIMEOUT_MS) {
    tiltActive = false;
    drive(0, 0);
  }

  // Stop if phone disconnects
  static bool wasConnected = false;
  bool connected = SerialBT.hasClient();
  if (wasConnected && !connected) {
    drive(0, 0);
    tiltActive = false;
    autoRunning = false;
  }
  wasConnected = connected;
}
