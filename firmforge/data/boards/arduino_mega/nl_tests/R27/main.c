// R27: SPI master 1MHz, send 0x00-0xFF, report MISO
#include <avr/io.h>
#include <util/delay.h>
#include <stdio.h>
#define BAUD 9600
#define UBRR_VAL ((F_CPU/16/BAUD)-1)
void uart_init(){UBRR0H=UBRR_VAL>>8;UBRR0L=UBRR_VAL;UCSR0B=1<<TXEN0;UCSR0C=(1<<UCSZ01)|(1<<UCSZ00);}
void uart_print(const char*s){while(*s){while(!(UCSR0A&(1<<UDRE0)));UDR0=*s++;}}
void spi_init(){DDRB|=(1<<2)|(1<<1)|(1<<0);SPCR=(1<<SPE)|(1<<MSTR)|(1<<SPR0);}
uint8_t spi_xfer(uint8_t d){SPDR=d;while(!(SPSR&(1<<SPIF)));return SPDR;}
int main(void){uart_init();spi_init();char b[48];uart_print("SPI START\r\n");for(uint16_t i=0;i<256;i++){uint8_t miso=spi_xfer((uint8_t)i);sprintf(b,"MOSI=0x%02X MISO=0x%02X\r\n",i,miso);uart_print(b);_delay_ms(10);}uart_print("DONE\r\n");while(1);}
