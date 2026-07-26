// R42: Dual tone PB5(OC1A) 440Hz, PB6(OC3A) 880Hz, alternate 500ms
#include <avr/io.h>
#include <util/delay.h>
#include <stdio.h>
#define BAUD 9600
#define UBRR_VAL ((F_CPU/16/BAUD)-1)
void uart_init(){UBRR0H=UBRR_VAL>>8;UBRR0L=UBRR_VAL;UCSR0B=1<<TXEN0;UCSR0C=(1<<UCSZ01)|(1<<UCSZ00);}
void uart_print(const char*s){while(*s){while(!(UCSR0A&(1<<UDRE0)));UDR0=*s++;}}
int main(void){
    uart_init();DDRB|=(1<<5)|(1<<6);
    // Toggle OC1A on match: f_out = F_CPU / (2 * prescaler * OCR)
    // 440Hz → OCR = 16e6/(2*1*440) - 1 = 18181
    TCCR1A=(1<<COM1A0);TCCR1B=(1<<WGM12)|(1<<CS10);OCR1A=18181;
    // 880Hz → OCR = 16e6/(2*1*880) - 1 = 9090
    TCCR3A=(1<<COM3A0);TCCR3B=(1<<WGM32)|(1<<CS30);OCR3A=9090;
    while(1){uart_print("A4\r\n");TCCR1A|=(1<<COM1A0);TCCR3A&=~(1<<COM3A0);_delay_ms(500);uart_print("A5\r\n");TCCR1A&=~(1<<COM1A0);TCCR3A|=(1<<COM3A0);_delay_ms(500);}
}
