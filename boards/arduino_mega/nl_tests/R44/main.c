// R44: DMM — ADC0 DC voltage + AC peak-to-peak
#include <avr/io.h>
#include <util/delay.h>
#include <stdio.h>
#define BAUD 9600
#define UBRR_VAL ((F_CPU/16/BAUD)-1)
void uart_init(){UBRR0H=UBRR_VAL>>8;UBRR0L=UBRR_VAL;UCSR0B=1<<TXEN0;UCSR0C=(1<<UCSZ01)|(1<<UCSZ00);}
void uart_print(const char*s){while(*s){while(!(UCSR0A&(1<<UDRE0)));UDR0=*s++;}}
uint16_t adc(){ADMUX=(1<<REFS0);ADCSRA=(1<<ADEN)|(1<<ADSC)|7;while(ADCSRA&(1<<ADSC));return ADC;}
int main(void){
    uart_init();char b[48];
    while(1){
        uint32_t sum=0;uint16_t mn=1023,mx=0;
        for(uint8_t i=0;i<100;i++){uint16_t v=adc();sum+=v;if(v<mn)mn=v;if(v>mx)mx=v;_delay_us(100);}
        uint16_t dc=sum/100,acpp=mx-mn;
        sprintf(b,"DC=%umV ACpp=%umV\r\n",dc*5000/1024,acpp*5000/1024);uart_print(b);
        _delay_ms(1000);
    }
}
