// R22: PCINT on PE4 — detect any pin change, report level
#include <avr/io.h>
#include <avr/interrupt.h>
#include <stdio.h>
#define BAUD 9600
#define UBRR_VAL ((F_CPU/16/BAUD)-1)
void uart_init(){UBRR0H=UBRR_VAL>>8;UBRR0L=UBRR_VAL;UCSR0B=1<<TXEN0;UCSR0C=(1<<UCSZ01)|(1<<UCSZ00);}
void uart_print(const char*s){while(*s){while(!(UCSR0A&(1<<UDRE0)));UDR0=*s++;}}
ISR(PCINT0_vect){uint8_t v=(PINE>>4)&1;char b[32];sprintf(b,"PIN_CHANGE:D=PE4 V=%u\r\n",v);uart_print(b);}
int main(void){uart_init();DDRE&=~(1<<4);PORTE|=(1<<4);PCICR|=(1<<PCIE0);PCMSK0|=(1<<PCINT4);sei();uart_print("READY\r\n");while(1);}
