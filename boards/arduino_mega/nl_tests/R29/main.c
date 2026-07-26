// R29: TWI I2C scan addresses 1-127, report found devices
#include <avr/io.h>
#include <util/delay.h>
#include <stdio.h>
#define BAUD 9600
#define UBRR_VAL ((F_CPU/16/BAUD)-1)
void uart_init(){UBRR0H=UBRR_VAL>>8;UBRR0L=UBRR_VAL;UCSR0B=1<<TXEN0;UCSR0C=(1<<UCSZ01)|(1<<UCSZ00);}
void uart_print(const char*s){while(*s){while(!(UCSR0A&(1<<UDRE0)));UDR0=*s++;}}
uint8_t i2c_start(){TWCR=(1<<TWINT)|(1<<TWSTA)|(1<<TWEN);while(!(TWCR&(1<<TWINT)));return TWSR&0xF8;}
uint8_t i2c_addr(uint8_t a,uint8_t rw){TWDR=(a<<1)|rw;TWCR=(1<<TWINT)|(1<<TWEN);while(!(TWCR&(1<<TWINT)));return TWSR&0xF8;}
void i2c_stop(){TWCR=(1<<TWINT)|(1<<TWSTO)|(1<<TWEN);}
int main(void){uart_init();uart_print("I2C SCAN\r\n");char b[32];uint8_t found=0;for(uint8_t a=1;a<128;a++){i2c_start();uint8_t s=i2c_addr(a,0);i2c_stop();if(s==0x18){sprintf(b,"DEVICE=0x%02X\r\n",a);uart_print(b);found++;}_delay_ms(2);}sprintf(b,"FOUND=%u\r\n",found);uart_print(b);while(1);}
