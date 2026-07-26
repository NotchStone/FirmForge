// R07: Uptime counter at 115200 baud, one per second
#include <avr/io.h>
#include <util/delay.h>
#include <stdio.h>

#define BAUD 115200
#define UBRR_VAL ((F_CPU/16/BAUD)-1)
void uart_init(){UBRR0H=UBRR_VAL>>8;UBRR0L=UBRR_VAL;UCSR0B=1<<TXEN0;UCSR0C=(1<<UCSZ01)|(1<<UCSZ00);}
void uart_print(const char*s){while(*s){while(!(UCSR0A&(1<<UDRE0)));UDR0=*s++;}}

int main(void){uart_init();uint32_t sec=0;char b[32];while(1){sprintf(b,"UPTIME=%lu s\r\n",sec++);uart_print(b);_delay_ms(1000);}}
