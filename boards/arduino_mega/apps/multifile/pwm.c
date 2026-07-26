// pwm.c — Timer0 Fast PWM on OC0A (PB7, pin 13 LED)
#include <avr/io.h>
#include "pwm.h"

void pwm_init(void) {
    DDRB |= (1 << 7);
    TCCR0A = (1 << WGM00) | (1 << WGM01) | (1 << COM0A1);
    TCCR0B = (1 << CS00);
}

void pwm_set(uint8_t duty) {
    OCR0A = duty;
}
