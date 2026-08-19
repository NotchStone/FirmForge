// pwm.h — Timer0 Fast PWM on OC0A (PB7)
#ifndef PWM_H
#define PWM_H

#include <stdint.h>

void pwm_init(void);
void pwm_set(uint8_t duty);

#endif
