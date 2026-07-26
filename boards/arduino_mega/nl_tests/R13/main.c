// R13: Timer1 CTC 1Hz interrupt, toggle LED, serial TICK
#include <avr/io.h>
#include <avr/interrupt.h>
#include <stdio.h>
#define BAUD 9600
#define UBRR_VAL ((F_CPU/16/BAUD)-1)
void uart_init(){UBRR0H=UBRR_VAL>>8;UBRR0L=UBRR_VAL;UCSR0B=1<<TXEN0;UCSR0C=(1<<UCSZ01)|(1<<UCSZ00);}
void uart_print(const char*s){while(*s){while(!(UCSR0A&(1<<UDRE0)));UDR0=*s++;}}
volatile uint8_t tick_flag=0;
ISR(TIMER1_COMPA_vect){tick_flag=1;}
int main(void){uart_init();DDRB|=(1<<7);OCR1A=15624;TCCR1B=(1<<WGM12)|(1<<CS12)|(1<<CS10);TIMSK1=(1<<OCIE1A);sei();while(1){if(tick_flag){tick_flag=0;PORTB^=(1<<7);uart_print("TICK\r\n");}}}
