// R06: Serial command LED control: ON/OFF/TOGGLE → LED PB7
#include <avr/io.h>
#include <string.h>

#define BAUD 9600
#define UBRR_VAL ((F_CPU/16/BAUD)-1)
void uart_init(){UBRR0H=UBRR_VAL>>8;UBRR0L=UBRR_VAL;UCSR0B=(1<<RXEN0)|(1<<TXEN0);UCSR0C=(1<<UCSZ01)|(1<<UCSZ00);}
void uart_tx(char c){while(!(UCSR0A&(1<<UDRE0)));UDR0=c;}
void uart_print(const char*s){while(*s)uart_tx(*s++);}
char uart_rx(){while(!(UCSR0A&(1<<RXC0)));return UDR0;}

int main(void) {
    uart_init();
    DDRB |= (1<<7);
    PORTB &= ~(1<<7);
    char cmd[8]; uint8_t idx=0;
    uart_print("CMD>\r\n");
    while(1){
        if(UCSR0A&(1<<RXC0)){
            char c=UDR0;
            if(c=='\r'||c=='\n'){
                cmd[idx]=0;
                if(!strcmp(cmd,"ON")){PORTB|=(1<<7);uart_print("ON\r\n");}
                else if(!strcmp(cmd,"OFF")){PORTB&=~(1<<7);uart_print("OFF\r\n");}
                else if(!strcmp(cmd,"TOGGLE")){PORTB^=(1<<7);uart_print("TOGGLE\r\n");}
                else{uart_print("UNKNOWN\r\n");}
                idx=0;
            }else if(idx<7){cmd[idx++]=c;}
        }
    }
}
