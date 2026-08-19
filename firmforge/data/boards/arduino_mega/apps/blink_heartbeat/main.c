// Blink Heartbeat — LED 1Hz + serial heartbeat counter
#include <avr/io.h>
#include <util/delay.h>
#include <stdio.h>

#define BAUD 9600
#define UBRR_VAL ((F_CPU / 16 / BAUD) - 1)

static void uart_init() {
    UBRR0H = UBRR_VAL >> 8;
    UBRR0L = UBRR_VAL;
    UCSR0B = (1 << TXEN0);
    UCSR0C = (1 << UCSZ01) | (1 << UCSZ00);
}
static void uart_tx(char c) {
    while (!(UCSR0A & (1 << UDRE0)));
    UDR0 = c;
}
static void uart_print(const char *s) {
    while (*s) uart_tx(*s++);
}

int main(void) {
    uart_init();
    DDRB |= (1 << 7);
    uart_print("BLINK START\r\n");

    uint16_t count = 0;
    char buf[32];

    while (1) {
        PORTB |= (1 << 7);
        sprintf(buf, "HB=%u ON\r\n", ++count);
        uart_print(buf);
        _delay_ms(500);

        PORTB &= ~(1 << 7);
        sprintf(buf, "HB=%u OFF\r\n", count);
        uart_print(buf);
        _delay_ms(500);
    }
}
