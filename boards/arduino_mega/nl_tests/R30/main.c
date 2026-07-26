// R30: I2C 24C02 EEPROM simulation — write pseudo-addr, read data
#include <avr/io.h>
#include <util/delay.h>
#include <stdio.h>
#define BAUD 9600
#define UBRR_VAL ((F_CPU/16/BAUD)-1)
void uart_init(){UBRR0H=UBRR_VAL>>8;UBRR0L=UBRR_VAL;UCSR0B=1<<TXEN0;UCSR0C=(1<<UCSZ01)|(1<<UCSZ00);}
void uart_print(const char*s){while(*s){while(!(UCSR0A&(1<<UDRE0)));UDR0=*s++;}}
void i2c_start(){TWCR=(1<<TWINT)|(1<<TWSTA)|(1<<TWEN);while(!(TWCR&(1<<TWINT)));}
void i2c_stop(){TWCR=(1<<TWINT)|(1<<TWSTO)|(1<<TWEN);}
uint8_t i2c_write(uint8_t d){TWDR=d;TWCR=(1<<TWINT)|(1<<TWEN);while(!(TWCR&(1<<TWINT)));return TWSR&0xF8;}
uint8_t i2c_read(uint8_t ack){TWCR=(1<<TWINT)|(1<<TWEN)|(ack?(1<<TWEA):0);while(!(TWCR&(1<<TWINT)));return TWDR;}
int main(void){uart_init();uart_print("I2C 24C02 SIM\r\n");char b[40];i2c_start();uint8_t s=i2c_write(0xA0);sprintf(b,"ADDR=0x%02X S=%u\r\n",s,s);uart_print(b);if(s==0x18){i2c_write(0x00);i2c_start();i2c_write(0xA1);uint8_t d=i2c_read(0);uart_print("DATA=");sprintf(b,"0x%02X",d);uart_print(b);uart_print("\r\n");}else{uart_print("NO DEVICE\r\n");}i2c_stop();while(1);}
