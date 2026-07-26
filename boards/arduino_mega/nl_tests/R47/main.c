// R47: Heartbeat LED 75BPM, ADC adjusts 60-120 BPM
#include <avr/io.h>
#include <avr/interrupt.h>
#include <util/delay.h>
#include <stdio.h>
#define BAUD 9600
#define UBRR_VAL ((F_CPU/16/BAUD)-1)
void uart_init(){UBRR0H=UBRR_VAL>>8;UBRR0L=UBRR_VAL;UCSR0B=1<<TXEN0;UCSR0C=(1<<UCSZ01)|(1<<UCSZ00);}
void uart_print(const char*s){while(*s){while(!(UCSR0A&(1<<UDRE0)));UDR0=*s++;}}
uint16_t adc(){ADMUX=(1<<REFS0);ADCSRA=(1<<ADEN)|(1<<ADSC)|7;while(ADCSRA&(1<<ADSC));return ADC;}
int main(void){
    uart_init();DDRB|=(1<<7);char b[32];
    while(1){
        uint16_t a=adc();uint16_t bpm=60+(a*60/1024);
        sprintf(b,"BPM=%u\r\n",bpm);uart_print(b);
        uint16_t bt=60000/bpm/2; // half-beat ms
        // lub-dub pattern: beat-pause-beat-longpause
        PORTB|=(1<<7);for(uint16_t i=0;i<bt/3;i++)_delay_ms(1);PORTB&=~(1<<7);for(uint16_t i=0;i<bt/3;i++)_delay_ms(1);
        PORTB|=(1<<7);for(uint16_t i=0;i<bt/3;i++)_delay_ms(1);PORTB&=~(1<<7);
        for(uint16_t i=0;i<bt;i++){_delay_ms(1);if(i%200==0){a=adc();bpm=60+(a*60/1024);bt=60000/bpm/2;}}
    }
}
