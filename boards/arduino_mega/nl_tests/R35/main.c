// R35: Alarm clock — serial SET/ALARM commands, Timer1 0.5s ticks
#include <avr/io.h>
#include <avr/interrupt.h>
#include <util/delay.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#define BAUD 9600
#define UBRR_VAL ((F_CPU/16/BAUD)-1)
void uart_init(){UBRR0H=UBRR_VAL>>8;UBRR0L=UBRR_VAL;UCSR0B=(1<<RXEN0)|(1<<TXEN0);UCSR0C=(1<<UCSZ01)|(1<<UCSZ00);}
void uart_print(const char*s){while(*s){while(!(UCSR0A&(1<<UDRE0)));UDR0=*s++;}}
char uart_getc(){while(!(UCSR0A&(1<<RXC0)));return UDR0;}
volatile uint8_t sec=0;
ISR(TIMER1_COMPA_vect){sec=1;}
int main(void){
    uart_init();DDRB|=(1<<7);
    OCR1A=7812;TCCR1B=(1<<WGM12)|(1<<CS12)|(1<<CS10);TIMSK1=(1<<OCIE1A);sei();
    uint8_t h=0,m=0,s=0,ah=0,am=0,alarm=0;char buf[48],ln[32];uint8_t i=0;
    uart_print(">\r\n");
    while(1){
        if(UCSR0A&(1<<RXC0)){char c=uart_getc();if(c=='\r'){ln[i]=0;i=0;if(strncmp(ln,"SET ",4)==0){int nh,nm,ns;if(sscanf(ln+4,"%d:%d:%d",&nh,&nm,&ns)==3){h=nh;m=nm;s=ns;}}else if(strncmp(ln,"ALARM ",6)==0){int nh,nm;if(sscanf(ln+6,"%d:%d",&nh,&nm)==2){ah=nh;am=nm;alarm=1;uart_print("ALARM SET\r\n");}}}else if(i<31)ln[i++]=c;}
        if(sec){sec=0;s++;if(s>=60){s=0;m++;if(m>=60){m=0;h++;if(h>=24)h=0;}}
            sprintf(buf,"%02d:%02d:%02d\r\n",h,m,s);uart_print(buf);
            if(alarm&&h==ah&&m==am&&s==0){
                DDRB|=(1<<6)|(1<<5)|(1<<4);
                for(uint8_t k=0;k<3;k++){for(uint8_t j=0;j<3;j++){PORTB|=(1<<7)|(1<<6);_delay_ms(100);PORTB&=~((1<<7)|(1<<6));_delay_ms(100);}_delay_ms(300);}
                uart_print("ALARM!\r\n");
            }
        }
    }
}
