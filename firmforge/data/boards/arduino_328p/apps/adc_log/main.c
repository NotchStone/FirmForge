#include <avr/io.h>
#include <avr/interrupt.h>
#include <util/delay.h>

static uint16_t g_counter = 0;

// UART 9600 8N1
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
    if (n == 0) { uart_char('0'); return; }
    while (n) { buf[--i] = '0' + (n % 10); n /= 10; }
    uart_str(&buf[i]);
}

// ADC read (10-bit, ch0 = A0, AVCC ref)
static uint16_t adc_read(void) {
    ADMUX = (1 << REFS0);  // AVCC ref, ADC0
    ADCSRA = (1 << ADEN) | (1 << ADPS2) | (1 << ADPS1) | (1 << ADPS0);  // enable, prescaler 128
    ADCSRA |= (1 << ADSC);  // start conversion
    while (ADCSRA & (1 << ADSC));  // wait
    return ADC;
}

int main(void) {
    uart_init();

    while (1) {
        g_counter++;
        uint16_t adc_val = adc_read();

        uart_str("["); uart_num(g_counter); uart_str("] ");
        uart_str("ADC0="); uart_num(adc_val);
        uart_str("\r\n");

        _delay_ms(1000);
    }
    return 0;
}
