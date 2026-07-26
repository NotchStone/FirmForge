// R08: Serial menu: 1=temp, 2=ADC, 3=toggle LED, ?=help
#include <avr/io.h>
#include <stdio.h>
#include <string.h>

#define BAUD 9600
#define UBRR_VAL ((F_CPU/16/BAUD)-1)
void uart_init(){UBRR0H=UBRR_VAL>>8;UBRR0L=UBRR_VAL;UCSR0B=(1<<RXEN0)|(1<<TXEN0);UCSR0C=(1<<UCSZ01)|(1<<UCSZ00);}
void uart_tx(char c){while(!(UCSR0A&(1<<UDRE0)));UDR0=c;}
void uart_print(const char*s){while(*s)uart_tx(*s++);}
uint16_t adc_read(){ADMUX=(1<<REFS0);ADCSRA=(1<<ADEN)|(1<<ADSC)|7;while(ADCSRA&(1<<ADSC));return ADC;}

int main(void){
    uart_init();
    DDRB|=(1<<7);PORTB&=~(1<<7);
    uart_print("1=Temp 2=ADC 3=LED ?=Help\r\n>");
    char b[32];
    while(1){
        if(UCSR0A&(1<<RXC0)){
            char c=UDR0;
            switch(c){
                case '1':sprintf(b,"Temp(ADC)=%u\r\n",adc_read());uart_print(b);break;
                case '2':sprintf(b,"ADC0=%u\r\n",adc_read());uart_print(b);break;
                case '3':PORTB^=(1<<7);uart_print(PORTB&(1<<7)?"LED=ON\r\n":"LED=OFF\r\n");break;
                case '?':uart_print("1=Temp 2=ADC 3=LED ?=Help\r\n");break;
                default:if(c>=' '){uart_print("CMD:");uart_tx(c);uart_tx('\r');uart_tx('\n');}
            }
            uart_tx('>');
        }
    }
}
