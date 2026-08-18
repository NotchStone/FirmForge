// R46: 74HC595 shift register simulation — DATA(PB0)/CLK(PB1)/LATCH(PB2)
#include <avr/io.h>
#include <util/delay.h>
#include <stdio.h>
#define BAUD 9600
#define UBRR_VAL ((F_CPU/16/BAUD)-1)
void uart_init(){UBRR0H=UBRR_VAL>>8;UBRR0L=UBRR_VAL;UCSR0B=1<<TXEN0;UCSR0C=(1<<UCSZ01)|(1<<UCSZ00);}
void uart_print(const char*s){while(*s){while(!(UCSR0A&(1<<UDRE0)));UDR0=*s++;}}
#define DATA (1<<0)
#define CLK (1<<1)
#define LATCH (1<<2)
void shift_out(uint8_t d){for(int8_t i=7;i>=0;i--){PORTB=(PORTB&~DATA)|((d>>i)&1?DATA:0);PORTB|=CLK;PORTB&=~CLK;}}
int main(void){
    uart_init();DDRB|=DATA|CLK|LATCH;char b[40];
    for(uint8_t d=0;d<255;d+=32){shift_out(d);PORTB|=LATCH;PORTB&=~LATCH;sprintf(b,"595 OUT=0x%02X\r\n",d);uart_print(b);_delay_ms(500);}
    uart_print("DONE\r\n");while(1);
}
