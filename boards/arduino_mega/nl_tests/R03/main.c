// R03: 4-LED running light, 200ms each
#include <avr/io.h>
#include <util/delay.h>

#define BAUD 9600
#define UBRR_VAL ((F_CPU / 16 / BAUD) - 1)
void uart_init(){UBRR0H=UBRR_VAL>>8;UBRR0L=UBRR_VAL;UCSR0B=1<<TXEN0;UCSR0C=(1<<UCSZ01)|(1<<UCSZ00);}
void uart_print(const char*s){while(*s){while(!(UCSR0A&(1<<UDRE0)));UDR0=*s++;}}

int main(void) {
    uart_init();
    DDRB |= (1 << 7) | (1 << 6) | (1 << 5) | (1 << 4); // PB4-7 LEDs
    PORTB &= ~0xF0;
    uart_print("START\r\n");
    while (1) {
        for (uint8_t i = 7; i >= 4; i--) {
            PORTB = (1 << i);
            uart_print("LED"); uart_print(i==7?"7":i==6?"6":i==5?"5":"4");
            uart_print("\r\n");
            _delay_ms(200);
        }
    }
}
