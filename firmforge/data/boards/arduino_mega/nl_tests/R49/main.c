// R49: Task scheduler — 1ms Timer1 ISR, Task A LED 1Hz, Task B ADC+UART
#include <avr/io.h>
#include <avr/interrupt.h>
#include <stdio.h>
#define BAUD 9600
#define UBRR_VAL ((F_CPU/16/BAUD)-1)
void uart_init(){UBRR0H=UBRR_VAL>>8;UBRR0L=UBRR_VAL;UCSR0B=1<<TXEN0;UCSR0C=(1<<UCSZ01)|(1<<UCSZ00);}
void uart_print(const char*s){while(*s){while(!(UCSR0A&(1<<UDRE0)));UDR0=*s++;}}
uint16_t adc(){ADMUX=(1<<REFS0);ADCSRA=(1<<ADEN)|(1<<ADSC)|7;while(ADCSRA&(1<<ADSC));return ADC;}
volatile uint32_t tick=0;
ISR(TIMER1_COMPA_vect){tick++;}
int main(void){
    uart_init();DDRB|=(1<<7);
    OCR1A=249;TCCR1B=(1<<WGM12)|(1<<CS11)|(1<<CS10);TIMSK1=(1<<OCIE1A);sei();
    uint32_t lastA=0,lastB=0;char b[32];
    while(1){
        if(tick-lastA>=500){lastA=tick;PORTB^=(1<<7);}
        if(tick-lastB>=1000){lastB=tick;uint16_t v=adc();sprintf(b,"T=%lu ADC=%u\r\n",tick,v);uart_print(b);}
    }
}
