// R12: Voltage monitor — ADC>512 → ALERT+LED, <512 → NORMAL-LED
#include <avr/io.h>
#include <util/delay.h>
#include <stdio.h>
#define BAUD 9600
#define UBRR_VAL ((F_CPU/16/BAUD)-1)
void uart_init(){UBRR0H=UBRR_VAL>>8;UBRR0L=UBRR_VAL;UCSR0B=1<<TXEN0;UCSR0C=(1<<UCSZ01)|(1<<UCSZ00);}
void uart_print(const char*s){while(*s){while(!(UCSR0A&(1<<UDRE0)));UDR0=*s++;}}
uint16_t adc_read(){ADMUX=(1<<REFS0);ADCSRA=(1<<ADEN)|(1<<ADSC)|7;while(ADCSRA&(1<<ADSC));return ADC;}
int main(void){uart_init();DDRB|=(1<<7);char b[32];uint8_t last=0;while(1){uint16_t v=adc_read();uint8_t alert=v>512;if(alert!=last){last=alert;sprintf(b,alert?"ADC=%u ALERT\r\n":"ADC=%u NORMAL\r\n",v);uart_print(b);PORTB=alert?(PORTB|(1<<7)):(PORTB&~(1<<7));}_delay_ms(200);}}
