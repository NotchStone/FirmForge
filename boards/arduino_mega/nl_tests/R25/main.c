// R25: Idle sleep, Timer1 wakes every 5s, toggle LED + serial WAKE
#include <avr/io.h>
#include <avr/interrupt.h>
#include <avr/sleep.h>
#include <util/delay.h>
#include <stdio.h>
#define BAUD 9600
#define UBRR_VAL ((F_CPU/16/BAUD)-1)
void uart_init(){UBRR0H=UBRR_VAL>>8;UBRR0L=UBRR_VAL;UCSR0B=1<<TXEN0;UCSR0C=(1<<UCSZ01)|(1<<UCSZ00);}
void uart_print(const char*s){while(*s){while(!(UCSR0A&(1<<UDRE0)));UDR0=*s++;}}
volatile uint8_t wake=0,count=0;
ISR(TIMER1_COMPA_vect){if(++count>=5){count=0;wake=1;}}
int main(void){uart_init();DDRB|=(1<<7);PORTB|=(1<<7);uart_print("LED ON\r\n");_delay_ms(2000);OCR1A=15624;TCCR1B=(1<<WGM12)|(1<<CS12)|(1<<CS10);TIMSK1=(1<<OCIE1A);set_sleep_mode(SLEEP_MODE_IDLE);sei();while(1){PORTB&=~(1<<7);uart_print("SLEEP\r\n");do{sleep_mode();}while(!wake);uart_print("WAKE\r\n");PORTB|=(1<<7);wake=0;}}
