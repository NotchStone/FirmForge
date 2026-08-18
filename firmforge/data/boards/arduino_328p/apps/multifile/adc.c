#include <avr/io.h>
#include "adc.h"

unsigned int adc_read(unsigned char ch) {
    ADMUX = (1 << REFS0) | (ch & 0x07);
    ADCSRA = (1 << ADEN) | (1 << ADPS2) | (1 << ADPS1) | (1 << ADPS0);
    ADCSRA |= (1 << ADSC);
    while (ADCSRA & (1 << ADSC));
    return ADC;
}
