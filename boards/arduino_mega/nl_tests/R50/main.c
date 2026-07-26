// R50: Mega composite — POST → WDT → EEPROM config → LED chase → ADC8 → report → main loop
#include <avr/io.h>
#include <avr/eeprom.h>
#include <avr/interrupt.h>
#include <util/delay.h>
#include <stdio.h>
#define BAUD 9600
#define UBRR_VAL ((F_CPU/16/BAUD)-1)
void uart_init(){UBRR0H=UBRR_VAL>>8;UBRR0L=UBRR_VAL;UCSR0B=(1<<RXEN0)|(1<<TXEN0);UCSR0C=(1<<UCSZ01)|(1<<UCSZ00);}
void uart_tx(char c){while(!(UCSR0A&(1<<UDRE0)));UDR0=c;}
void uart_print(const char*s){while(*s)uart_tx(*s++);}
uint16_t adc(uint8_t ch){ADMUX=(1<<REFS0)|(ch&7);ADCSRA=(1<<ADEN)|(1<<ADSC)|7;while(ADCSRA&(1<<ADSC));return ADC;}
volatile uint8_t mode=0;
ISR(INT0_vect){mode=(mode+1)%3;}

int main(void){
    uart_init();char b[48];
    // POST
    uint8_t rst=MCUSR;MCUSR=0;sprintf(b,"POST: RESET=0x%02x\r\n",rst);uart_print(b);
    uint16_t boot=eeprom_read_word(0);boot++;eeprom_write_word(0,boot);
    sprintf(b,"BOOT_COUNT=%u\r\n",boot);uart_print(b);
    // WDT 4s
    WDTCSR=(1<<WDCE)|(1<<WDE);WDTCSR=(1<<WDE)|(1<<WDP3);
    // LED chase 3 rounds
    DDRB|=0xF0;for(uint8_t r=0;r<3;r++)for(uint8_t i=7;i>=4;i--){PORTB=(1<<i);_delay_ms(100);__asm__("wdr");}
    // ADC 8 channels
    uart_print("ADC:\r\n");for(uint8_t ch=0;ch<8;ch++){sprintf(b,"  CH%d=%u\r\n",ch,adc(ch));uart_print(b);__asm__("wdr");}
    uart_print("READY\r\n");
    // INT0 for mode switching
    DDRD&=~(1<<0);PORTD|=(1<<0);EICRA|=(1<<ISC01);EIMSK|=(1<<INT0);sei();
    while(1){__asm__("wdr");uart_tx('0'+mode);uart_print("> ADC=");sprintf(b,"%u\r\n",adc(0));uart_print(b);_delay_ms(2000);}
}
