// R36: Data logger — ADC ring buffer 16 in EEPROM, DUMP/CLEAR commands
#include <avr/io.h>
#include <avr/eeprom.h>
#include <util/delay.h>
#include <stdio.h>
#include <string.h>
#define BAUD 9600
#define UBRR_VAL ((F_CPU/16/BAUD)-1)
void uart_init(){UBRR0H=UBRR_VAL>>8;UBRR0L=UBRR_VAL;UCSR0B=(1<<RXEN0)|(1<<TXEN0);UCSR0C=(1<<UCSZ01)|(1<<UCSZ00);}
void uart_print(const char*s){while(*s){while(!(UCSR0A&(1<<UDRE0)));UDR0=*s++;}}
char uart_getc(){while(!(UCSR0A&(1<<RXC0)));return UDR0;}
uint16_t adc(){ADMUX=(1<<REFS0);ADCSRA=(1<<ADEN)|(1<<ADSC)|7;while(ADCSRA&(1<<ADSC));return ADC;}
int main(void){
    uart_init();char b[32];uint8_t idx=0;uint16_t eepos=0;
    uart_print("LOGGER>\r\n");
    while(1){
        if(UCSR0A&(1<<RXC0)){char c=uart_getc();char cmd[8];uint8_t ci=0;while(c!='\r'&&ci<7)cmd[ci++]=uart_getc();cmd[ci]=0;
        if(!strcmp(cmd,"DUMP")){for(uint8_t i=0;i<16;i++){uint16_t v=eeprom_read_word((uint16_t*)(i*2));sprintf(b,"[%2d]=%u\r\n",i,v);uart_print(b);}}
        else if(!strcmp(cmd,"CLEAR")){for(uint8_t i=0;i<32;i++)eeprom_write_byte((uint8_t*)i,0);idx=0;uart_print("CLEARED\r\n");}
        uart_print("LOGGER>\r\n");}
        uint16_t val=adc();eeprom_write_word((uint16_t*)(idx*2),val);sprintf(b,"LOG[%d]=%u\r\n",idx,val);uart_print(b);idx=(idx+1)&15;_delay_ms(1000);
    }
}
