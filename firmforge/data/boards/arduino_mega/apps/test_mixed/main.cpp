#include <Arduino.h>

void uart_send(char c) {
    while (!(UCSR0A & (1 << UDRE0)));
    UDR0 = c;
}
void uart_msg(const char* s) {
    while (*s) uart_send(*s++);
}

void setup() {
    UBRR0H = 0; UBRR0L = 103;
    UCSR0B = (1 << TXEN0); UCSR0C = (1 << UCSZ01) | (1 << UCSZ00);
    pinMode(13, OUTPUT);
    uart_msg("TEST_MIXED:START\n");
    digitalWrite(13, HIGH); delay(300);
    digitalWrite(13, LOW); delay(300);
    uart_msg("TEST_MIXED:PASS\n");
}
void loop() {}
