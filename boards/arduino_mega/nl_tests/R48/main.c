// R48: Exception handler — trap unexpected interrupts, report SREG
#include <avr/io.h>
#include <avr/interrupt.h>
#include <stdio.h>
#define BAUD 9600
#define UBRR_VAL ((F_CPU/16/BAUD)-1)
void uart_init(){UBRR0H=UBRR_VAL>>8;UBRR0L=UBRR_VAL;UCSR0B=1<<TXEN0;UCSR0C=(1<<UCSZ01)|(1<<UCSZ00);}
void uart_print(const char*s){while(*s){while(!(UCSR0A&(1<<UDRE0)));UDR0=*s++;}}
// Catch Timer4, Timer5 COMPA as "unexpected" ISR handlers
ISR(TIMER4_COMPA_vect){char b[32];sprintf(b,"EXCEPTION: TIMER4_COMPA SREG=0x%02x\r\n",SREG);uart_print(b);}
ISR(TIMER5_COMPA_vect){char b[32];sprintf(b,"EXCEPTION: TIMER5_COMPA SREG=0x%02x\r\n",SREG);uart_print(b);}
int main(void){uart_init();uart_print("Exception handlers registered\r\n");while(1);}
