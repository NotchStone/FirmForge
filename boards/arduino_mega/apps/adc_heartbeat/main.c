// ADC Heartbeat — ADC1 value ×3/×5/×10 ms → LED blink + serial trace
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
static uint16_t adc_read(uint8_t ch) {
    ADMUX = (1 << REFS0) | (ch & 7);
    ADCSRA = (1 << ADEN) | (1 << ADSC) | 7;
    while (ADCSRA & (1 << ADSC));
    return ADC;
}

int main(void) {
    uart_init();
    DDRB |= (1 << 7);              // LED = PB7
    uart_print("ADC Heartbeat v3/v5/v10\r\n");

    uint16_t hb = 0;
    char buf[48];
    uint8_t multipliers[] = {3, 5, 10};

    while (1) {
        uint16_t adc = adc_read(1);  // ADC channel 1
        hb++;
        uint16_t t3 = adc * 3, t5 = adc * 5, t10 = adc * 10;

        for (uint8_t i = 0; i < 3; i++) {
            uint16_t period = adc * multipliers[i];
            uint16_t half = period / 2;
            if (half < 10) half = 10;

            PORTB |= (1 << 7);
            for (uint16_t t = 0; t < half; t++) _delay_ms(1);
            PORTB &= ~(1 << 7);
            for (uint16_t t = 0; t < half; t++) _delay_ms(1);
        }

        // One output per heartbeat cycle
        sprintf(buf, "HB=%u ADC=%u T=%u/%u/%u ms\r\n",
                hb, adc, t3, t5, t10);
        uart_print(buf);
    }
}
