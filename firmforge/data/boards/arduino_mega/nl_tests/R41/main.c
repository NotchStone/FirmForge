// R41: Adaptive light — ADC LDR input, PWM LED fill light (darker = brighter)
#include <avr/io.h>
#include <util/delay.h>
#include <stdio.h>
#define BAUD 9600
#define UBRR_VAL ((F_CPU/16/BAUD)-1)
void uart_init(){UBRR0H=UBRR_VAL>>8;UBRR0L=UBRR_VAL;UCSR0B=1<<TXEN0;UCSR0C=(1<<UCSZ01)|(1<<UCSZ00);}
void uart_print(const char*s){while(*s){while(!(UCSR0A&(1<<UDRE0)));UDR0=*s++;}}
uint16_t adc(){ADMUX=(1<<REFS0);ADCSRA=(1<<ADEN)|(1<<ADSC)|7;while(ADCSRA&(1<<ADSC));return ADC;}
int main(void){
    uart_init();DDRB|=(1<<7);
    TCCR0A=(1<<WGM00)|(1<<WGM01)|(1<<COM0A1);TCCR0B=(1<<CS00);
    char b[40];
    while(1){uint16_t l=adc();uint8_t pwm=255-(uint32_t)l*255/1024;sprintf(b,"L=%u PWM=%u%%\r\n",l,pwm*100/255);uart_print(b);OCR0A=pwm;_delay_ms(2000);}
}
