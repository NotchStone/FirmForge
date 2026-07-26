// R02: Button input (pull-up), LED=on when pressed, serial on change
#include <avr/io.h>
#include <util/delay.h>

#define BAUD 9600
#define UBRR_VAL ((F_CPU / 16 / BAUD) - 1)

void uart_init() {
    UBRR0H = (UBRR_VAL >> 8);
    UBRR0L = UBRR_VAL;
    UCSR0B = (1 << TXEN0);
    UCSR0C = (1 << UCSZ01) | (1 << UCSZ00);
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
    DDRB |= (1 << 7);          // LED = PB7 output
    PORTB &= ~(1 << 7);        // LED off
    DDRE &= ~(1 << 4);         // Button = PE4 input
    PORTE |= (1 << 4);         // Enable pull-up

    uint8_t last = (PINE >> 4) & 1;
    uart_print(last ? "RELEASED\r\n" : "PRESSED\r\n");

    while (1) {
        uint8_t now = (PINE >> 4) & 1;
        if (now != last) {
            last = now;
            if (now) {
                PORTB &= ~(1 << 7);
                uart_print("RELEASED\r\n");
            } else {
                PORTB |= (1 << 7);
                uart_print("PRESSED\r\n");
            }
        }
        _delay_ms(10);
    }
}
