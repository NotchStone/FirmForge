// uart.c — USART0 on ATmega2560
#include <avr/io.h>
#include "uart.h"

#define BAUD 9600
#define UBRR_VAL ((F_CPU / 16 / BAUD) - 1)

void uart_init(void) {
    UBRR0H = UBRR_VAL >> 8;
    UBRR0L = UBRR_VAL;
    UCSR0B = (1 << TXEN0);
    UCSR0C = (1 << UCSZ01) | (1 << UCSZ00);
}

void uart_putchar(char c) {
    while (!(UCSR0A & (1 << UDRE0)));
    UDR0 = c;
}

void uart_print(const char *s) {
    while (*s) uart_putchar(*s++);
}
