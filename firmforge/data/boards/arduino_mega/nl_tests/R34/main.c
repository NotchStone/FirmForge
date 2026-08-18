// R34: Stopwatch — button PE4, Timer1 0.1s, 4 LED carry, UART time
#include <avr/io.h>
#include <avr/interrupt.h>
#include <util/delay.h>
#include <stdio.h>
#define BAUD 9600
#define UBRR_VAL ((F_CPU/16/BAUD)-1)
void uart_init(){UBRR0H=UBRR_VAL>>8;UBRR0L=UBRR_VAL;UCSR0B=1<<TXEN0;UCSR0C=(1<<UCSZ01)|(1<<UCSZ00);}
void uart_tx(char c){while(!(UCSR0A&(1<<UDRE0)));UDR0=c;}
void uart_print(const char*s){while(*s)uart_tx(*s++);}
volatile uint16_t ds=0;
ISR(TIMER1_COMPA_vect){ds++;}
int main(void){
    uart_init();DDRB|=0xF0;DDRE&=~(1<<4);PORTE|=(1<<4);
    OCR1A=1562;TCCR1B=(1<<WGM12)|(1<<CS12)|(1<<CS10);TIMSK1=(1<<OCIE1A);
    sei();char b[32];uint8_t run=0,last=1,_t;
    while(1){
        uint8_t now=(PINE>>4)&1;
        if(!now&&last){if(!run){ds=0;run=1;uart_print("START\r\n");}else{run=0;uart_print("STOP\r\n");}_delay_ms(200);}
        last=now;
        if(run){uint16_t t=ds/10;_t=t%10;uint8_t pb=0x00;if(_t>=5)pb|=0x80;if(t%10>=5)pb|=0x40;if((t/10)%6>=3)pb|=0x20;if(t>=3600)pb|=0x10;PORTB=(PORTB&0x0F)|pb;sprintf(b,"T=%d.%d\r\n",t/10,_t);uart_print(b);}
        _delay_ms(200);
    }
}
