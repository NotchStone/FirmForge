#include <avr/io.h>
#include <util/delay.h>

// UART init 9600 8N1
static void uart_init(void) {
    UBRR0H = 0;
    UBRR0L = 103;  // 9600 @ 16MHz
    UCSR0B = (1 << TXEN0);
    UCSR0C = (1 << UCSZ01) | (1 << UCSZ00);
}

static void uart_char(char c) {
    while (!(UCSR0A & (1 << UDRE0)));
    UDR0 = c;
}

static void uart_str(const char *s) {
    while (*s) uart_char(*s++);
}

static void uart_num(uint16_t n) {
    char buf[6];
    int i = 5;
    buf[5] = 0;
    do {
        buf[--i] = '0' + (n % 10);
        n /= 10;
    } while (n);
    uart_str(&buf[i]);
}

int main(void) {
    uart_init();
    uint16_t counter = 0;

    while (1) {
        uart_str("NO:");
        uart_num(counter);
        uart_str(" OK\r\n");
        counter++;
        _delay_ms(500);
    }
    return 0;
}
