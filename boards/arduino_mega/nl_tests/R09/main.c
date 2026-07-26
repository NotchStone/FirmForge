// R09: ADC0 raw + voltage output every second
#include <avr/io.h>
#include <util/delay.h>
#include <stdio.h>

#define BAUD 9600
#define UBRR_VAL ((F_CPU/16/BAUD)-1)
void uart_init(){UBRR0H=UBRR_VAL>>8;UBRR0L=UBRR_VAL;UCSR0B=1<<TXEN0;UCSR0C=(1<<UCSZ01)|(1<<UCSZ00);}
void uart_print(const char*s){while(*s){while(!(UCSR0A&(1<<UDRE0)));UDR0=*s++;}}
uint16_t adc_read(){ADMUX=(1<<REFS0);ADCSRA=(1<<ADEN)|(1<<ADSC)|7;_delay_us(200);while(ADCSRA&(1<<ADSC));return ADC;}

int main(void){
    uart_init();
    char b[40];
    while(1){
        uint16_t raw=adc_read();
        uint16_t mv=(uint32_t)raw*5000/1024;
        sprintf(b,"ADC=%u mV=%u\r\n",raw,mv);
        uart_print(b);
        _delay_ms(1000);
    }
}
