// blink — ATmega328P bare register LED on PB5 (pin 13)
#define F_CPU 16000000UL
#include <avr/io.h>
#include <util/delay.h>
#include <stdio.h>

static void uart_init(unsigned long baud) {
    uint16_t ubrr = F_CPU / 16 / baud - 1;
    UBRR0H = ubrr >> 8; UBRR0L = ubrr; UCSR0B = (1 << TXEN0);
    UCSR0C = (1 << UCSZ01) | (1 << UCSZ00);
}
static void uart_putchar(char c) { while (!(UCSR0A & (1 << UDRE0))); UDR0 = c; }
static void uart_print(const char *s) { while (*s) uart_putchar(*s++); }

int main(void) {
    DDRB |= (1 << 5);
    uart_init(9600);
    uart_print("BLINK 328P\r\n");
    uint16_t cnt = 0; char buf[32];
    while (1) {
        PORTB |= (1 << 5); _delay_ms(1000);
        PORTB &= ~(1 << 5); _delay_ms(1000);
        sprintf(buf, "HB=%u ON\r\n", ++cnt); uart_print(buf);
        sprintf(buf, "HB=%u OFF\r\n", ++cnt); uart_print(buf);
    }
}
