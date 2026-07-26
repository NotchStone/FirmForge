// R45: Serial bootloader protocol — parse S:ADDR:LEN:DATA:CRC
#include <avr/io.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#define BAUD 9600
#define UBRR_VAL ((F_CPU/16/BAUD)-1)
void uart_init(){UBRR0H=UBRR_VAL>>8;UBRR0L=UBRR_VAL;UCSR0B=(1<<RXEN0)|(1<<TXEN0);UCSR0C=(1<<UCSZ01)|(1<<UCSZ00);}
void uart_print(const char*s){while(*s){while(!(UCSR0A&(1<<UDRE0)));UDR0=*s++;}}
char uart_getc(){while(!(UCSR0A&(1<<RXC0)));return UDR0;}
int main(void){
    uart_init();char b[80],ln[64];uint8_t i=0;
    uart_print("BOOT>\r\n");
    while(1){
        if(UCSR0A&(1<<RXC0)){char c=uart_getc();if(c=='\r'){ln[i]=0;i=0;
        if(ln[0]=='S'&&ln[1]==':'){
            uint16_t addr,len,data,crc;
            if(sscanf(ln,"S:%x:%x:%x:%x",&addr,&len,&data,&crc)==4){
                uint16_t calc=addr+len+data;
                sprintf(b,"ADDR=0x%04X LEN=%u DATA=0x%04X CRC=%s\r\n",addr,len,data,calc==crc?"OK":"FAIL");uart_print(b);
            }}}else if(i<63)ln[i++]=c;uart_print("BOOT>\r\n");}}
}
