// Adaptive Night Light — ADC0 LDR → inverse PWM LED + serial trace
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
    DDRB |= (1 << 7);                    // LED = OC0A (PB7)
    TCCR0A = (1 << WGM00) | (1 << WGM01) | (1 << COM0A1);
    TCCR0B = (1 << CS00);                // Fast PWM, no prescale

    uart_print("NIGHT LIGHT\r\n");

    uint16_t hb = 0;
    char buf[48];

    while (1) {
        uint16_t light = adc_read(0);   // 0=dark, 1023=bright
        uint8_t duty = 255 - (uint32_t)light * 255 / 1024; // inverse
        OCR0A = duty;
        hb++;

        uint8_t level;
        const char *label;
        if (duty < 64)      { level = 9 - duty * 9 / 64;  label = "BRIGHT"; }
        else if (duty < 128) { level = 5;                   label = "OVERCAST"; }
        else if (duty < 192) { level = 3;                   label = "DUSK"; }
        else                 { level = 1;                   label = "DARK"; }

        sprintf(buf, "HB=%u LUX=%u DUTY=%u%% L=%u %s\r\n",
                hb, light, duty * 100 / 255, level, label);
        uart_print(buf);

        _delay_ms(2000);
    }
}
