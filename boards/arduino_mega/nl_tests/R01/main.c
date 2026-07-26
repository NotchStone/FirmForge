// R01: LED blink 500ms on/off with serial output
#include <avr/io.h>
#include <util/delay.h>

#define BAUD 9600
#define UBRR_VAL ((F_CPU / 16 / BAUD) - 1)

void uart_init() {
    UBRR0H = (UBRR_VAL >> 8);
    UBRR0L = UBRR_VAL;
    UCSR0B = (1 << TXEN0);
    UCSR0C = (1 << UCSZ01) | (1 << UCSZ00); // 8N1
}

void uart_tx(char c) {
    while (!(UCSR0A & (1 << UDRE0)));
    UDR0 = c;
}

void uart_print(const char *s) {
    while (*s) uart_tx(*s++);
}

int main(void) {
    uart_init();
    DDRB |= (1 << 7); // LED on PB7

    while (1) {
        PORTB |= (1 << 7);
        uart_print("ON\r\n");
        _delay_ms(500);
        PORTB &= ~(1 << 7);
        uart_print("OFF\r\n");
        _delay_ms(500);
    }
}
