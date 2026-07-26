// R14: PWM breathing LED, 4s cycle, serial brightness %
#include <avr/io.h>
#include <util/delay.h>
#include <stdio.h>
#define BAUD 9600
#define UBRR_VAL ((F_CPU/16/BAUD)-1)
void uart_init(){UBRR0H=UBRR_VAL>>8;UBRR0L=UBRR_VAL;UCSR0B=1<<TXEN0;UCSR0C=(1<<UCSZ01)|(1<<UCSZ00);}
void uart_print(const char*s){while(*s){while(!(UCSR0A&(1<<UDRE0)));UDR0=*s++;}}
int main(void){uart_init();DDRB|=(1<<7);TCCR0A=(1<<WGM00)|(1<<WGM01)|(1<<COM0A1);TCCR0B=(1<<CS00);char b[32];while(1){for(int16_t i=0;i<256;i++){OCR0A=i;sprintf(b,"%d%%\r\n",i*100/255);uart_print(b);_delay_ms(8);}for(int16_t i=254;i>=0;i--){OCR0A=i;sprintf(b,"%d%%\r\n",i*100/255);uart_print(b);_delay_ms(8);}}}
