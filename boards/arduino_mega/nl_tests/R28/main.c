// R28: SPI master — send 0x55 read-status, read 2 bytes response
#include <avr/io.h>
#include <stdio.h>
#define BAUD 9600
#define UBRR_VAL ((F_CPU/16/BAUD)-1)
void uart_init(){UBRR0H=UBRR_VAL>>8;UBRR0L=UBRR_VAL;UCSR0B=1<<TXEN0;UCSR0C=(1<<UCSZ01)|(1<<UCSZ00);}
void uart_print(const char*s){while(*s){while(!(UCSR0A&(1<<UDRE0)));UDR0=*s++;}}
void spi_init(){DDRB|=(1<<2)|(1<<1)|(1<<0);SPCR=(1<<SPE)|(1<<MSTR)|(1<<SPR0);}
uint8_t spi_xfer(uint8_t d){SPDR=d;while(!(SPSR&(1<<SPIF)));return SPDR;}
int main(void){uart_init();spi_init();char b[48];uart_print("SPI CMD=0x55\r\n");uint8_t d0=spi_xfer(0x55);uint8_t d1=spi_xfer(0x00);uint8_t d2=spi_xfer(0x00);sprintf(b,"STATUS=0x%02X DATA=0x%02X%02X\r\n",d0,d1,d2);uart_print(b);while(1);}
