#include <Arduino.h>
void setup() { Serial.begin(9600); Serial.println("START"); ADMUX=(1<<REFS0); ADCSRA=(1<<ADEN)|(1<<ADPS2)|(1<<ADPS1)|(1<<ADPS0); }
void loop() { ADCSRA|=(1<<ADSC); while(ADCSRA&(1<<ADSC)); uint16_t r=ADC; float v=r*5.0/1023.0; Serial.print("ADC="); Serial.print(r); Serial.print(" V="); Serial.println(v,2); delay(1000); }
