#include <avr/io.h>
#include "pwm.h"

void pwm_init(void) {
    DDRB |= (1 << PB1);
    TCCR1A = (1 << COM1A1) | (1 << WGM10);
    TCCR1B = (1 << WGM12) | (1 << CS10);
    OCR1A = 0;
}

void pwm_set(unsigned char duty) {
    OCR1A = (unsigned int)duty;
}
