#include <Arduino.h>
unsigned long prev=0;bool led=false;const int interval=500;
void setup(){Serial.begin(9600);Serial.println("START");DDRB|=(1<<7);}
void loop(){unsigned long t=millis();if(t-prev>=interval){prev=t;led=!led;if(led)PORTB|=(1<<7);else PORTB&=~(1<<7);Serial.println(led?"ON":"OFF");}}