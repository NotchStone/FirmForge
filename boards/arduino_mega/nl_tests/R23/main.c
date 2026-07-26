// R23: Watchdog 2s, feed every 1s. Reports reset cause via MCUSR.
#include <avr/io.h>
#include <avr/interrupt.h>
#include <util/delay.h>
#include <stdio.h>
#define BAUD 9600
#define UBRR_VAL ((F_CPU/16/BAUD)-1)
void uart_init(){UBRR0H=UBRR_VAL>>8;UBRR0L=UBRR_VAL;UCSR0B=1<<TXEN0;UCSR0C=(1<<UCSZ01)|(1<<UCSZ00);}
void uart_print(const char*s){while(*s){while(!(UCSR0A&(1<<UDRE0)));UDR0=*s++;}}
int main(void){uart_init();DDRB|=(1<<7);char b[32];uint8_t rst=MCUSR;MCUSR=0;sprintf(b,"RESET=0x%02x\r\n",rst);uart_print(b);WDTCSR=(1<<WDCE)|(1<<WDE);WDTCSR=(1<<WDE)|(1<<WDP2)|(1<<WDP1)|(1<<WDP0);uint16_t ticks=0;while(1){__asm__("wdr");uart_print("FEED\r\n");_delay_ms(1000);ticks++;if(ticks>=5){uart_print("HALTING\r\n");while(1);}}}
