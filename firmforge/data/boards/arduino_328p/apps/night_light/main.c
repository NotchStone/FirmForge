// night_light — ATmega328P ADC+PWM heartbeat
// A0 reads LDR, PB1 (pin 9) drives PWM LED via OCR1A
// Serial output on USART0 (pins 0,1)

#define F_CPU 16000000UL
#include <avr/io.h>
#include <util/delay.h>
#include <stdio.h>

static void uart_init(unsigned long baud) {
    uint16_t ubrr = F_CPU / 16 / baud - 1;
    UBRR0H = ubrr >> 8;
    UBRR0L = ubrr;
    UCSR0B = (1 << TXEN0);
    UCSR0C = (1 << UCSZ01) | (1 << UCSZ00);
}

static void uart_putchar(char c) {
    while (!(UCSR0A & (1 << UDRE0)));
    UDR0 = c;
}

static void uart_print(const char *s) {
    while (*s) uart_putchar(*s++);
}

static void adc_init(void) {
    ADMUX = (1 << REFS0);
    ADCSRA = (1 << ADEN) | 7;
}

static uint16_t adc_read(uint8_t ch) {
    ADMUX = (1 << REFS0) | (ch & 7);
    ADCSRA |= (1 << ADSC);
    while (ADCSRA & (1 << ADSC));
    return ADC;
}

static void pwm_init(void) {
    DDRB |= (1 << 1);
    TCCR1A = (1 << WGM10) | (1 << COM1A1);
    TCCR1B = (1 << WGM12) | (1 << CS10);
}

static void pwm_set(uint16_t val) {
    OCR1A = val;
}

int main(void) {
    uart_init(9600);
    adc_init();
    pwm_init();

    uart_print("NIGHT LIGHT 328P\r\n");

    uint16_t hb = 0;
    char buf[48];

    while (1) {
        uint16_t light = adc_read(0);
        uint16_t pwm_val = light > 1023 ? 1023 : light;
        pwm_set(pwm_val);
        hb++;

        sprintf(buf, "HB=%u LUX=%u PWM=%u\r\n",
                hb, light, pwm_val);
        uart_print(buf);
        _delay_ms(2000);
    }
}
