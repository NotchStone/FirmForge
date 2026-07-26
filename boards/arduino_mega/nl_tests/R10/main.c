// R10: ADC0 value changes LED (PB7) blink frequency
#include <avr/io.h>
#include <util/delay.h>
#include <stdio.h>

#define BAUD 9600
#define UBRR_VAL ((F_CPU/16/BAUD)-1)
void uart_init(){UBRR0H=UBRR_VAL>>8;UBRR0L=UBRR_VAL;UCSR0B=1<<TXEN0;UCSR0C=(1<<UCSZ01)|(1<<UCSZ00);}
void uart_tx(char c){while(!(UCSR0A&(1<<UDRE0)));UDR0=c;}
void uart_print(const char*s){while(*s)uart_tx(*s++);}
uint16_t adc_read(){ADMUX=(1<<REFS0);ADCSRA=(1<<ADEN)|(1<<ADSC)|7;while(ADCSRA&(1<<ADSC));return ADC;}

int main(void){
    uart_init();DDRB|=(1<<7);
    char b[32];
    while(1){
        uint16_t adc=adc_read();
        uint16_t ms=100+(adc*900/1023); // 100ms (ADC=0) → 1000ms (ADC=1023)
        sprintf(b,"ADC=%u T=%ums\r\n",adc,ms);
        uart_print(b);
        PORTB|=(1<<7); for(uint16_t i=0;i<ms/10;i++)_delay_ms(10);
        PORTB&=~(1<<7); for(uint16_t i=0;i<ms/10;i++)_delay_ms(10);
    }
}
