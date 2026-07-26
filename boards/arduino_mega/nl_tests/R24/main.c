// R24: Watchdog demo — normal 5s then hang → reset → LED flash 3x
#include <avr/io.h>
#include <avr/interrupt.h>
#include <avr/sleep.h>
#include <util/delay.h>
#include <stdio.h>
#define BAUD 9600
#define UBRR_VAL ((F_CPU/16/BAUD)-1)
void uart_init(){UBRR0H=UBRR_VAL>>8;UBRR0L=UBRR_VAL;UCSR0B=1<<TXEN0;UCSR0C=(1<<UCSZ01)|(1<<UCSZ00);}
void uart_print(const char*s){while(*s){while(!(UCSR0A&(1<<UDRE0)));UDR0=*s++;}}
int main(void){uart_init();DDRB|=(1<<7);char b[32];uint8_t rst=MCUSR;MCUSR=0;if(rst&(1<<WDRF)){for(int i=0;i<3;i++){PORTB|=(1<<7);_delay_ms(100);PORTB&=~(1<<7);_delay_ms(100);}uart_print("WDT RESET!\r\n");while(1);}WDTCSR=(1<<WDCE)|(1<<WDE);WDTCSR=(1<<WDE)|(1<<WDP1)|(1<<WDP0);uart_print("RUNNING 5s\r\n");for(int i=0;i<5;i++){__asm__("wdr");_delay_ms(1000);}uart_print("DEADLOCK\r\n");while(1);}
