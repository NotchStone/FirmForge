// R15: Timer3 CTC 1kHz square wave on PE3 (OC3A), print config
#include <avr/io.h>
#include <stdio.h>
#define BAUD 9600
#define UBRR_VAL ((F_CPU/16/BAUD)-1)
void uart_init(){UBRR0H=UBRR_VAL>>8;UBRR0L=UBRR_VAL;UCSR0B=1<<TXEN0;UCSR0C=(1<<UCSZ01)|(1<<UCSZ00);}
void uart_print(const char*s){while(*s){while(!(UCSR0A&(1<<UDRE0)));UDR0=*s++;}}
int main(void){uart_init();DDRE|=(1<<3);OCR3A=7;TCCR3A=(1<<COM3A0);TCCR3B=(1<<WGM32)|(1<<CS30);uart_print("Timer3 CTC 1kHz OC3A(PE3) CS=1 OCR=8\r\n");while(1);}
