// R31: MCUSR reset cause — power, external, watchdog, brownout
#include <avr/io.h>
#include <stdio.h>
#define BAUD 9600
#define UBRR_VAL ((F_CPU/16/BAUD)-1)
void uart_init(){UBRR0H=UBRR_VAL>>8;UBRR0L=UBRR_VAL;UCSR0B=1<<TXEN0;UCSR0C=(1<<UCSZ01)|(1<<UCSZ00);}
void uart_print(const char*s){while(*s){while(!(UCSR0A&(1<<UDRE0)));UDR0=*s++;}}
int main(void){uart_init();uint8_t r=MCUSR;MCUSR=0;char b[40];uart_print("RESET:");if(r&(1<<PORF))uart_print(" POWER");if(r&(1<<EXTRF))uart_print(" EXT");if(r&(1<<BORF))uart_print(" BROWNOUT");if(r&(1<<WDRF))uart_print(" WATCHDOG");if(r==0)uart_print(" UNKNOWN");sprintf(b," (0x%02x)\r\n",r);uart_print(b);while(1);}
