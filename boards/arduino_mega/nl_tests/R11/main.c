// R11: Rotate 4 ADC channels (0-3), 1 per second
#include <avr/io.h>
#include <util/delay.h>
#include <stdio.h>
#define BAUD 9600
#define UBRR_VAL ((F_CPU/16/BAUD)-1)
void uart_init(){UBRR0H=UBRR_VAL>>8;UBRR0L=UBRR_VAL;UCSR0B=1<<TXEN0;UCSR0C=(1<<UCSZ01)|(1<<UCSZ00);}
void uart_print(const char*s){while(*s){while(!(UCSR0A&(1<<UDRE0)));UDR0=*s++;}}
uint16_t adc_read(uint8_t ch){ADMUX=(1<<REFS0)|(ch&7);ADCSRA=(1<<ADEN)|(1<<ADSC)|7;while(ADCSRA&(1<<ADSC));return ADC;}
int main(void){uart_init();char b[32];uint8_t ch=0;while(1){sprintf(b,"CH=%u ADC=%u\r\n",ch,adc_read(ch));uart_print(b);ch=(ch+1)&3;_delay_ms(1000);}}
