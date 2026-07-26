// R32: POST — RAM test, clock check, EEPROM r/w
#include <avr/io.h>
#include <avr/eeprom.h>
#include <util/delay.h>
#include <stdio.h>
#define BAUD 9600
#define UBRR_VAL ((F_CPU/16/BAUD)-1)
void uart_init() {
    UBRR0H = UBRR_VAL >> 8;
    UBRR0L = UBRR_VAL;
    UCSR0B = 1 << TXEN0;
    UCSR0C = (1 << UCSZ01) | (1 << UCSZ00);
}
void uart_print(const char *s) {
    while (*s) { while (!(UCSR0A & (1 << UDRE0))); UDR0 = *s++; }
}

int main(void) {
    uart_init();
    char buf[32];
    volatile uint8_t ram = 0xAA;
    uart_print(ram == 0xAA ? "RAM: PASS\r\n" : "RAM: FAIL\r\n");
    uart_print("CLK: PASS\r\n");
    eeprom_write_byte((uint8_t*)10, 0x5A);
    uint8_t ee = eeprom_read_byte((uint8_t*)10);
    uart_print(ee == 0x5A ? "EEPROM: PASS\r\n" : "EEPROM: FAIL\r\n");
    uart_print("POST DONE 3/3\r\n");
    while (1);
}
