#include <Arduino.h>
// Auto-generated prototypes
void blink;

// Auto-generated prototypes
void blink;

// Auto-generated prototypes
void blink;


void blink() {
    digitalWrite(13, HIGH);
    delay(200);
    digitalWrite(13, LOW);
    delay(200);
}

void setup() {
    Serial.begin(9600);
    pinMode(13, OUTPUT);
    Serial.println("TEST_PURE_API:START");
    blink();
    Serial.println("TEST_PURE_API:PASS");
}

void loop() {}
