// Define the GPIO pin connected to the LED
// GPIO 2 is the default built-in LED pin on most standard ESP32 boards
const int ledPin = 2; 

void setup() {
  // Configure the LED pin as an output pin
  pinMode(ledPin, OUTPUT);
}

void loop() {
  digitalWrite(ledPin, HIGH); // Turn the LED ON (HIGH voltage level)
  delay(1000);                // Wait for 1000 milliseconds (1 second)
  
  digitalWrite(ledPin, LOW);  // Turn the LED OFF (LOW voltage level)
  delay(1000);                // Wait for 1 second
}
