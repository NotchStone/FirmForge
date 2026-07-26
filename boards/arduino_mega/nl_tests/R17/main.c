// R17: Servo PWM Timer1 50Hz, serial angle command 0-180 (Mega2560)
#include <avr/io.h>
#include <avr/interrupt.h>
#include <stdio.h>
#include <stdlib.h>

#define BAUD 9600
#define UBRR_VAL ((F_CPU / 16 / BAUD) - 1)

void uart_init() {
    UBRR0H = UBRR_VAL >> 8;
    UBRR0L = UBRR_VAL;
    UCSR0B = (1 << RXEN0) | (1 << TXEN0);
    UCSR0C = (1 << UCSZ01) | (1 << UCSZ00);
}
void uart_print(const char *s) {
    while (*s) {
        while (!(UCSR0A & (1 << UDRE0)));
        UDR0 = *s++;
    }
}
char uart_rx() {
    while (!(UCSR0A & (1 << RXC0)));
    return UDR0;
}
void servo_set(uint16_t us) {
    OCR1A = us * 2;  // 2 counts/us at 2MHz clock (prescaler 8, 16MHz/8=2MHz)
}

int main(void) {
    uart_init();
    DDRB |= (1 << 5);  // OC1A = PB5
    // Fast PWM 50Hz, ICR1=39999
    TCCR1A = (1 << COM1A1) | (1 << WGM11);
    TCCR1B = (1 << WGM13) | (1 << WGM12) | (1 << CS11);
    ICR1 = 39999;
    servo_set(1500);  // center

    char buf[32];
    uint16_t angle = 0;
    uart_print("ANGLE>\r\n");

    while (1) {
        if (UCSR0A & (1 << RXC0)) {
            char c = uart_rx();
            if (c >= '0' && c <= '9') {
                angle = angle * 10 + (c - '0');
            } else if (c == '\r') {
                if (angle > 180) angle = 180;
                uint16_t pw = 1000 + (uint32_t)angle * 1000 / 180;
                sprintf(buf, "Angle=%u PWM=%uus\r\n", angle, pw);
                uart_print(buf);
                servo_set(pw);
                angle = 0;
                uart_print("ANGLE>\r\n");
            }
        }
    }
}
