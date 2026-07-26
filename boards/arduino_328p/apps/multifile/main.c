#include <avr/io.h>
#include <avr/interrupt.h>
#include <util/delay.h>
#include <stdio.h>
#include "uart.h"
#include "adc.h"
#include "pwm.h"

static volatile unsigned char heartbeat = 0;

ISR(TIMER0_COMPA_vect) {
    heartbeat++;
}

int main(void) {
    char buf[64];
    uart_init(9600);
    adc_read(0);
    pwm_init();

    // Timer0: 1-second heartbeat
    TCCR0A = (1 << WGM01);
    TCCR0B = (1 << CS02) | (1 << CS00);
    OCR0A = 156;
    TIMSK0 = (1 << OCIE0A);
    sei();

    while (1) {
        unsigned int lux_raw = adc_read(0);
        unsigned int lux = (unsigned int)((unsigned long)lux_raw * 500 / 1023);
        unsigned char pwm_val = (unsigned char)lux_raw * 255 / 1023;
        pwm_set(pwm_val);

        snprintf(buf, sizeof(buf), "HB=%u LUX=%u PWM=%u\r\n", heartbeat, lux, pwm_val);
        uart_print(buf);

        _delay_ms(2000);
    }
    return 0;
}
