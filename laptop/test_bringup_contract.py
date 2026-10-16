"""Keep the Arduino bench sketch on the same safe hardware contract as firmware."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BRINGUP = (ROOT / "firmware" / "bringup.txt").read_text(encoding="utf-8")
PINS = (ROOT / "firmware" / "pins.h").read_text(encoding="utf-8")


def test_bringup_uses_the_pca_i2c_bus_from_the_real_firmware():
    # Camera owns Wire1; the PCA9685 shares the primary Wire controller on GPIO 39/40.
    assert "Wire1" not in BRINGUP
    assert "Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL, 400000);" in BRINGUP
    assert "Wire.beginTransmission(PCA_ADDR);" in BRINGUP


def test_bringup_motor_pins_match_the_production_pin_plan():
    for declaration in (
        "MOTOR_L_EN = 38, MOTOR_L_IN1 = 2, MOTOR_L_IN2 = 47",
        "MOTOR_R_EN = 48, MOTOR_R_IN1 = 21, MOTOR_R_IN2 = 14",
    ):
        assert declaration in BRINGUP
    for declaration in (
        "PIN_MOTOR_L_EN = 38",
        "PIN_MOTOR_L_IN1 = 2",
        "PIN_MOTOR_L_IN2 = 47",
        "PIN_MOTOR_R_EN = 48",
        "PIN_MOTOR_R_IN1 = 21",
        "PIN_MOTOR_R_IN2 = 14",
    ):
        assert declaration in PINS


def test_bringup_allows_unwired_sensors_without_touching_invalid_gpio():
    assert "IR_OBSTACLE_L = -1, IR_OBSTACLE_R = -1, IR_FLAME_L = 46" in BRINGUP
    assert "return pin < 0 ? -1 : digitalRead(pin);" in BRINGUP
    assert "if (pin >= 0) pinMode(pin, INPUT);" in BRINGUP
