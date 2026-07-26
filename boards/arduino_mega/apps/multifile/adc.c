// adc.c — ADC driver (ATmega2560)
#include <avr/io.h>
#include <stdint.h>
#include "adc.h"

void adc_init(void) {
    ADMUX = (1 << REFS0);
    ADCSRA = (1 << ADEN) | 7;
}

uint16_t adc_read(uint8_t channel) {
    ADMUX = (1 << REFS0) | (channel & 7);
    ADCSRA |= (1 << ADSC);
    while (ADCSRA & (1 << ADSC));
    return ADC;
}
