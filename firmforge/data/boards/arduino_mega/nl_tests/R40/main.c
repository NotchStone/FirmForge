// R40: Morse code — serial text input, LED flash, echo dots/dashes
#include <avr/io.h>
#include <util/delay.h>
#include <stdio.h>
#include <string.h>
#include <ctype.h>
#define BAUD 9600
#define UBRR_VAL ((F_CPU / 16 / BAUD) - 1)

const char *MC[] = {
    ".-","-...","-.-.","-..",".","..-.","--.","....","..",".---",
    "-.-",".-..","--","-.","---",".--.","--.-",".-.","...","-",
    "..-","...-",".--","-..-","-.--","--.."
};

void uart_init() { UBRR0H = UBRR_VAL >> 8; UBRR0L = UBRR_VAL; UCSR0B = (1<<RXEN0)|(1<<TXEN0); UCSR0C = (1<<UCSZ01)|(1<<UCSZ00); }
void uart_tx(char c) { while (!(UCSR0A & (1<<UDRE0))); UDR0 = c; }
char uart_rx() { while (!(UCSR0A & (1<<RXC0))); return UDR0; }
void uart_print(const char *s) { while (*s) uart_tx(*s++); }
void dot() { PORTB |= (1<<7); _delay_ms(200); PORTB &= ~(1<<7); _delay_ms(200); }
void dash() { PORTB |= (1<<7); _delay_ms(600); PORTB &= ~(1<<7); _delay_ms(200); }

int main(void) {
    uart_init(); DDRB |= (1<<7);
    char buf[32]; uint8_t i = 0;
    uart_print("TEXT>\r\n");
    while (1) {
        if (UCSR0A & (1<<RXC0)) {
            char c = uart_rx();
            if (c == '\r') {
                buf[i] = 0; i = 0;
                for (uint8_t j = 0; buf[j]; j++) {
                    if (isalpha(buf[j])) {
                        uint8_t idx = toupper(buf[j]) - 'A';
                        const char *code = MC[idx];
                        uart_tx(toupper(buf[j])); uart_tx(':');
                        for (uint8_t k = 0; code[k]; k++) {
                            uart_tx(code[k]); uart_tx(' ');
                            if (code[k] == '.') dot(); else dash();
                        }
                        uart_print("\r\n");
                    }
                }
                uart_print("TEXT>\r\n");
            } else if (i < 31) buf[i++] = c;
        }
    }
}
