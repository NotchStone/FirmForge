// R39: ADC 100 samples → ASCII bar chart waveform via serial
#include <avr/io.h>
#include <util/delay.h>
#include <stdio.h>
#define BAUD 9600
#define UBRR_VAL ((F_CPU/16/BAUD)-1)
void uart_init(){UBRR0H=UBRR_VAL>>8;UBRR0L=UBRR_VAL;UCSR0B=1<<TXEN0;UCSR0C=(1<<UCSZ01)|(1<<UCSZ00);}
void uart_tx(char c){while(!(UCSR0A&(1<<UDRE0)));UDR0=c;}
uint16_t adc(){ADMUX=(1<<REFS0);ADCSRA=(1<<ADEN)|(1<<ADSC)|7;while(ADCSRA&(1<<ADSC));return ADC;}
int main(void){
    uart_init();uint16_t buf[100];char bar[41];
    while(1){
        for(uint8_t i=0;i<100;i++){buf[i]=adc();_delay_us(200);}
        uart_tx('\r');uart_tx('\n');
        for(uint8_t i=0;i<100;i++){uint8_t h=buf[i]*40/1024;for(uint8_t j=0;j<40;j++)bar[j]=j<h?'#':' ';bar[40]=0;char str[44];sprintf(str,"%03d:%04u|%s\r\n",i,buf[i],bar);for(char*p=str;*p;uart_tx(*p++));}
        _delay_ms(2000);
    }
}
