#include <Arduino.h>
void setup(){Serial.begin(9600);Serial.println("START");DDRB|=(1<<7);}void loop(){PORTB|=(1<<7);Serial.println("ON");delay(1000);PORTB&=~(1<<7);Serial.println("OFF");delay(1000);}