#include <Arduino.h>

int cnt = 0;

void setup() {
    Serial.begin(9600);
    Serial.println("ARDUINO 328P");
}

void loop() {
    cnt++;
    Serial.print("HB=");
    Serial.print(cnt);
    Serial.println(" HELLO");
    delay(2000);
}
