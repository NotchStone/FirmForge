// R18: EEPROM save/restore LED state on button press
#include <avr/io.h>
#include <avr/eeprom.h>
#include <util/delay.h>
#include <stdio.h>
#define BAUD 9600
#define UBRR_VAL ((F_CPU/16/BAUD)-1)
void uart_init(){UBRR0H=UBRR_VAL>>8;UBRR0L=UBRR_VAL;UCSR0B=1<<TXEN0;UCSR0C=(1<<UCSZ01)|(1<<UCSZ00);}
void uart_print(const char*s){while(*s){while(!(UCSR0A&(1<<UDRE0)));UDR0=*s++;}}
int main(void){uart_init();DDRB|=(1<<7);DDRE&=~(1<<4);PORTE|=(1<<4);uint8_t st=eeprom_read_byte(0);if(st)PORTB|=(1<<7);else PORTB&=~(1<<7);char b[32];sprintf(b,st?"BOOT: LED=ON\r\n":"BOOT: LED=OFF\r\n");uart_print(b);uint8_t last=(PINE>>4)&1;while(1){uint8_t now=(PINE>>4)&1;if(!now&&last){PORTB^=(1<<7);uint8_t s=(PORTB>>7)&1;eeprom_write_byte(0,s);sprintf(b,"SAVE: LED=%s\r\n",s?"ON":"OFF");uart_print(b);_delay_ms(50);}last=now;_delay_ms(5);}}
