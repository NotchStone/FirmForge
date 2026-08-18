#include <Arduino.h>
void setup(){Serial.begin(9600);Serial.println("START");DDRD&=~(1<<0);PORTD|=(1<<0);}void loop(){int b=PIND&(1<<0);Serial.println(b?"HIGH":"LOW");delay(100);}