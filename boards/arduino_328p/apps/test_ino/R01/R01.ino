#include <Arduino.h>
void setup() { Serial.begin(9600); Serial.println("START"); pinMode(13, OUTPUT); }
void loop() { digitalWrite(13, HIGH); Serial.println("ON"); delay(500); digitalWrite(13, LOW); Serial.println("OFF"); delay(500); }
