// R43: 4-ch PWM — Timer1 PB5/6/7, Timer3 PE3/4/5, each different duty
#include <avr/io.h>
#include <stdio.h>
#define BAUD 9600
#define UBRR_VAL ((F_CPU/16/BAUD)-1)
void uart_init(){UBRR0H=UBRR_VAL>>8;UBRR0L=UBRR_VAL;UCSR0B=1<<TXEN0;UCSR0C=(1<<UCSZ01)|(1<<UCSZ00);}
void uart_print(const char*s){while(*s){while(!(UCSR0A&(1<<UDRE0)));UDR0=*s++;}}
int main(void){
    uart_init();DDRB|=(1<<7)|(1<<6)|(1<<5);DDRE|=(1<<3);
    // Timer0 PWM on PB7 (OC0A)
    TCCR0A=(1<<WGM00)|(1<<WGM01)|(1<<COM0A1);TCCR0B=(1<<CS00);
    // Timer1 10-bit PWM on PB5(OC1A), PB6(OC1B)
    TCCR1A=(1<<COM1A1)|(1<<COM1B1)|(1<<WGM11);TCCR1B=(1<<WGM13)|(1<<WGM12)|(1<<CS10);ICR1=1023;
    // Timer3 10-bit PWM on PE3(OC3A)
    TCCR3A=(1<<COM3A1)|(1<<WGM31);TCCR3B=(1<<WGM33)|(1<<WGM32)|(1<<CS30);ICR3=1023;
    OCR0A=64;OCR1A=256;OCR1B=512;OCR3A=768;
    char b[48];sprintf(b,"PWM 25%%/25%%/50%%/75%%\r\n");uart_print(b);
    while(1);
}
