// main.c — Multi-file demo: ADC light → PWM LED + UART heartbeat
#include <util/delay.h>
#include <stdio.h>
#include "uart.h"
#include "adc.h"
#include "pwm.h"

int main(void) {
    uart_init();
    adc_init();
    pwm_init();

    uart_print("MULTIFILE START\r\n");

    uint16_t hb = 0;
    char buf[48];

    while (1) {
        uint16_t light = adc_read(0);
        uint8_t duty = (uint8_t)(light >> 2);  // 10-bit → 8-bit
        pwm_set(duty);
        hb++;

        sprintf(buf, "HB=%u LUX=%u PWM=%u%%\r\n",
                hb, light, duty * 100 / 255);
        uart_print(buf);
        _delay_ms(1000);
    }
}
