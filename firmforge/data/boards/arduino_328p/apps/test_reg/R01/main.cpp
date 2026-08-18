#include <Arduino.h>
void setup() { Serial.begin(9600); Serial.println("START"); DDRB |= (1<<5); }
void loop() { PORTB |= (1<<5); Serial.println("ON"); delay(500); PORTB &= ~(1<<5); Serial.println("OFF"); delay(500); }
