// R37: RGB LED rainbow — 3 PWM channels sinusoidal
#include <avr/io.h>
#include <util/delay.h>
#include <math.h>
#include <stdio.h>
#define BAUD 9600
#define UBRR_VAL ((F_CPU/16/BAUD)-1)
void uart_init(){UBRR0H=UBRR_VAL>>8;UBRR0L=UBRR_VAL;UCSR0B=1<<TXEN0;UCSR0C=(1<<UCSZ01)|(1<<UCSZ00);}
void uart_print(const char*s){while(*s){while(!(UCSR0A&(1<<UDRE0)));UDR0=*s++;}}
int main(void){
    uart_init();DDRB|=(1<<7)|(1<<6)|(1<<5);
    TCCR0A=(1<<WGM00)|(1<<WGM01)|(1<<COM0A1);TCCR0B=(1<<CS00);
    TCCR1A=(1<<COM1A1)|(1<<COM1B1)|(1<<WGM11);TCCR1B=(1<<WGM13)|(1<<WGM12)|(1<<CS10);ICR1=255;
    char b[32];uint16_t phi=0;
    while(1){
        uint8_t r=128+(int16_t)(127*sin((phi+0)*M_PI/180));
        uint8_t g=128+(int16_t)(127*sin((phi+120)*M_PI/180));
        uint8_t bv=128+(int16_t)(127*sin((phi+240)*M_PI/180));
        OCR0A=r;OCR1A=g;OCR1B=bv;
        sprintf(b,"R=%u G=%u B=%u\r\n",r,g,bv);uart_print(b);
        phi=(phi+2)%360;_delay_ms(40);
    }
}
