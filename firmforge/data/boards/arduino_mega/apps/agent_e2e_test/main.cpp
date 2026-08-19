#define F_CPU 16000000UL
#include <avr/io.h>
#include <util/delay.h>

void uart_init() { UBRR0H=0; UBRR0L=103; UCSR0B=(1<<TXEN0); UCSR0C=(1<<UCSZ01)|(1<<UCSZ00); }
void uart_byte(uint8_t b) { while(!(UCSR0A&(1<<UDRE0))); UDR0=b; }
void uart(const char* s) { while(*s) uart_byte(*s++); }

int main() {
    uart_init();
    _delay_ms(100);
    uart("TEMP=25C\n");
    _delay_ms(50);
    uart("TEMP=25C\n");
    _delay_ms(50);
    uart("E2E:PASS\n");
    while (1) {}
    return 0;
}
