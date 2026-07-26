// R19: EEPROM boot counter — read, increment, display, write
#include <avr/io.h>
#include <avr/eeprom.h>
#include <stdio.h>
#define BAUD 9600
#define UBRR_VAL ((F_CPU/16/BAUD)-1)
void uart_init(){UBRR0H=UBRR_VAL>>8;UBRR0L=UBRR_VAL;UCSR0B=1<<TXEN0;UCSR0C=(1<<UCSZ01)|(1<<UCSZ00);}
void uart_print(const char*s){while(*s){while(!(UCSR0A&(1<<UDRE0)));UDR0=*s++;}}
int main(void){uart_init();uint16_t cnt=eeprom_read_word(0);cnt++;eeprom_write_word(0,cnt);char b[32];sprintf(b,"BOOT_COUNT=%u\r\n",cnt);uart_print(b);while(1);}
