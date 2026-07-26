// R20: EEPROM config — READ N / WRITE N V via serial
#include <avr/io.h>
#include <avr/eeprom.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#define BAUD 9600
#define UBRR_VAL ((F_CPU/16/BAUD)-1)
void uart_init(){UBRR0H=UBRR_VAL>>8;UBRR0L=UBRR_VAL;UCSR0B=(1<<RXEN0)|(1<<TXEN0);UCSR0C=(1<<UCSZ01)|(1<<UCSZ00);}
void uart_print(const char*s){while(*s){while(!(UCSR0A&(1<<UDRE0)));UDR0=*s++;}}
char rx_buf[32];uint8_t rx_i;
char rx_char(){while(!(UCSR0A&(1<<RXC0)));return UDR0;}
int main(void){uart_init();char b[32];uart_print("EEPROM>");rx_i=0;while(1){if(UCSR0A&(1<<RXC0)){char c=rx_char();if(c=='\r'){rx_buf[rx_i]=0;char cmd[8];int n=0,v=0;if(sscanf(rx_buf,"%s %d %d",cmd,&n,&v)>=2){if(!strcmp(cmd,"READ")){sprintf(b,"[%d]=%u\r\n",n,eeprom_read_byte((uint8_t*)n));uart_print(b);}else if(!strcmp(cmd,"WRITE")){eeprom_write_byte((uint8_t*)n,(uint8_t)v);sprintf(b,"WRITE %d=%d OK\r\n",n,v);uart_print(b);}else uart_print("CMD: READ N / WRITE N V\r\n");}else uart_print("CMD: READ N / WRITE N V\r\n");rx_i=0;uart_print("EEPROM>");}else if(rx_i<31){rx_buf[rx_i++]=c;}}}}
