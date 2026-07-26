#define F_CPU 16000000UL
#include <avr/io.h>
#include <util/delay.h>

void uart_init() {
    UBRR0H = 0;
    UBRR0L = 103;  // 9600 baud @ 16MHz
    UCSR0B = (1 << TXEN0);
    UCSR0C = (1 << UCSZ01) | (1 << UCSZ00);
}

void uart_byte(uint8_t b) {
    while (!(UCSR0A & (1 << UDRE0)));
    UDR0 = b;
}

void uart_str(const char* s) {
    while (*s) uart_byte(*s++);
}

void uart_nl() { uart_str("\r\n"); }

int main() {
    uart_init();
    _delay_ms(500);

    uint16_t beat = 0;
    while (1) {
        uart_str("--- HEARTBEAT #");
        char buf[8];
        uint16_t n = beat;
        buf[6] = '0' + (n % 10); n /= 10;
        buf[5] = '0' + (n % 10); n /= 10;
        buf[4] = '0' + (n % 10); n /= 10;
        buf[3] = '0' + (n % 10); n /= 10;
        buf[2] = '0' + (n % 10);
        uint8_t start = 2;
        while (start < 6 && buf[start] == '0') start++;
        for (uint8_t i = start; i < 7; i++) uart_byte(buf[i]);
        uart_nl();

        uart_str("  **     **  "); uart_nl();
        uart_str(" ****   **** "); uart_nl();
        uart_str("****** ******"); uart_nl();
        uart_str(" *********** "); uart_nl();
        uart_str("  *********  "); uart_nl();
        uart_str("   *******   "); uart_nl();
        uart_str("    *****    "); uart_nl();
        uart_str("     ***     "); uart_nl();
        uart_str("      *      "); uart_nl();

        beat++;
        _delay_ms(1500);
    }
    return 0;
}
