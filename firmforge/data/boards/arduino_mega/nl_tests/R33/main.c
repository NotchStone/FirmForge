// R33: Thermostat — ADC temp, PWM fan, serial output
#include <avr/io.h>
#include <util/delay.h>
#include <stdio.h>
#define BAUD 9600
#define UBRR_VAL ((F_CPU/16/BAUD)-1)
void uart_init(){UBRR0H=UBRR_VAL>>8;UBRR0L=UBRR_VAL;UCSR0B=1<<TXEN0;UCSR0C=(1<<UCSZ01)|(1<<UCSZ00);}
void uart_print(const char*s){while(*s){while(!(UCSR0A&(1<<UDRE0)));UDR0=*s++;}}
uint16_t adc(){ADMUX=(1<<REFS0);ADCSRA=(1<<ADEN)|(1<<ADSC)|7;while(ADCSRA&(1<<ADSC));return ADC;}
int main(void){uart_init();DDRB|=(1<<7);TCCR0A=(1<<WGM00)|(1<<WGM01)|(1<<COM0A1);TCCR0B=(1<<CS00);char b[48];while(1){uint16_t t=adc();uint8_t pwm=0;if(t>614)pwm=255;else if(t>410)pwm=(t-410)*255/204;sprintf(b,"ADC=%u PWM=%u%%\r\n",t,pwm*100/255);uart_print(b);OCR0A=pwm;_delay_ms(1000);}}
