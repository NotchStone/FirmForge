#include <Arduino.h>

void setup() {
    Serial.begin(9600);
    pinMode(13, OUTPUT);
    Serial.println("TEST_ARDUINO_INO:START");
    digitalWrite(13, HIGH);
    Serial.println("LED=ON");
    delay(500);
    digitalWrite(13, LOW);
    Serial.println("LED=OFF");
    Serial.println("TEST_ARDUINO_INO:PASS");
}

void loop() {
    // Nothing
}
