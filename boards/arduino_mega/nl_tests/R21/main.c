// R21: INT0 (PD0) falling edge → toggle LED + serial BUTTON:PRESSED
#include <avr/io.h>
#include <avr/interrupt.h>
#define BAUD 9600
#define UBRR_VAL ((F_CPU/16/BAUD)-1)
void uart_init(){UBRR0H=UBRR_VAL>>8;UBRR0L=UBRR_VAL;UCSR0B=1<<TXEN0;UCSR0C=(1<<UCSZ01)|(1<<UCSZ00);}
void uart_print(const char*s){while(*s){while(!(UCSR0A&(1<<UDRE0)));UDR0=*s++;}}
ISR(INT0_vect){PORTB^=(1<<7);uart_print("BUTTON:PRESSED\r\n");}
int main(void){uart_init();DDRB|=(1<<7);DDRD&=~(1<<0);PORTD|=(1<<0);EICRA|=(1<<ISC01);EIMSK|=(1<<INT0);sei();uart_print("READY\r\n");while(1);}
