// Boot report for the rover board. It does nothing else: no Wi-Fi, no camera, no motors, no servos.
//
//   python -m platformio run -d firmware -e diag -t upload
//   python -m platformio device monitor -b 115200
//
// It prints once a second on BOTH serial ports, so you cannot be looking at the wrong one:
//   - the native "USB" port of the board (this is where the real firmware prints, because
//     ARDUINO_USB_CDC_ON_BOOT=1), and
//   - the "UART" port (where the ROM boot lines appear).
// Each line says why the board started, how much PSRAM it found, and the level of every
// strapping pin. Strapping pins are read once at reset to choose how the chip starts, so one held
// high by a wire or a module (an I2C pull-up, a sensor output) can stop it booting properly.
//
// What to look for:
//   reset reason POWERON every time it repeats = the chip loses power or a strapping pin is wrong
//   reset reason PANIC / WDT / BROWNOUT         = the program crashed or the supply sagged
//   psram 0 bytes                                = the PSRAM setting in platformio.ini is wrong
//   gpio45 or gpio3 = 1 with nothing meant to drive them = a wire is holding a strapping pin high
#include <Arduino.h>
#include <esp_system.h>
#include <stdarg.h>

static void say(const char* format, ...) {
  char line[200];
  va_list args;
  va_start(args, format);
  vsnprintf(line, sizeof line, format, args);
  va_end(args);
  Serial.println(line);
#if ARDUINO_USB_CDC_ON_BOOT
  Serial0.println(line);  // Serial is the native USB port: also print on the UART port
#endif
}

static const char* resetName(esp_reset_reason_t reason) {
  switch (reason) {
    case ESP_RST_POWERON: return "POWERON (power was applied or the board was reset by hand)";
    case ESP_RST_SW: return "SW (the program asked for a restart)";
    case ESP_RST_PANIC: return "PANIC (the program crashed)";
    case ESP_RST_INT_WDT: return "INT_WDT (interrupt watchdog)";
    case ESP_RST_TASK_WDT: return "TASK_WDT (a task hung)";
    case ESP_RST_WDT: return "WDT (watchdog)";
    case ESP_RST_BROWNOUT: return "BROWNOUT (the supply voltage sagged)";
    case ESP_RST_DEEPSLEEP: return "DEEPSLEEP";
    default: return "other";
  }
}

void setup() {
  Serial.begin(115200);
#if ARDUINO_USB_CDC_ON_BOOT
  Serial0.begin(115200);
#endif
  delay(1500);  // the native USB port needs a moment before it shows anything
}

void loop() {
  static uint32_t count = 0;
  const int strapPins[] = {0, 3, 45, 46};
  say("---- boot report %u ----", static_cast<unsigned>(++count));
  say("reset reason : %s", resetName(esp_reset_reason()));
  say("chip         : %s rev %d, flash %u MB", ESP.getChipModel(), ESP.getChipRevision(),
      static_cast<unsigned>(ESP.getFlashChipSize() / (1024 * 1024)));
  say("psram        : %u bytes (the N16R8 should show about 8388608)", static_cast<unsigned>(ESP.getPsramSize()));
  say("free heap    : %u bytes", static_cast<unsigned>(ESP.getFreeHeap()));
  for (int pin : strapPins) {
    pinMode(pin, INPUT);
    say("gpio%-2d       : %d%s", pin, digitalRead(pin),
        (pin == 45 || pin == 3) ? "   <- strapping pin: should be 0 with nothing wired to it" : "");
  }
  delay(1000);
}
