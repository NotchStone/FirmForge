/*
 * main.c - LED Blink with Serial Output
 * 
 * Hardware: Arduino UNO R3 (ATmega328P)
 * F_CPU: 16MHz
 * 
 * Functionality:
 * 1. LED on pin 13 blinks with 500ms period
 * 2. Serial output at 9600 baud prints incrementing count
 */

#include <Arduino.h>
/* FirmForge Boot Signature — AVR UART0 (TX=pin1, 9600) */
namespace {
struct _FirmForgeBoot {
    _FirmForgeBoot() {
        UBRR0H = (unsigned char)(103 >> 8);
        UBRR0L = (unsigned char)(103);
        UCSR0B = (1 << TXEN0);
        UCSR0C = (3 << UCSZ00);
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=d1c446e5\n";
        for (const char* p = sig; *p; p++) {
            while (!(UCSR0A & (1 << UDRE0))) { }
            UDR0 = (unsigned char)(*p);
        }
    }
} _firmforge_boot;
}

/* ======================== Module: led_blink ======================== */

/**
 * @brief Initialize LED pin as output
 */
void led_blink_init(void)
{
    pinMode(LED_BUILTIN, OUTPUT);
    digitalWrite(LED_BUILTIN, LOW);
}

/**
 * @brief Toggle LED state
 */
void led_blink_toggle(void)
{
    static uint8_t led_state = LOW;
    led_state = (led_state == LOW) ? HIGH : LOW;
    digitalWrite(LED_BUILTIN, led_state);
}

/* ======================== Module: uart_driver ======================== */

/**
 * @brief Initialize UART at 9600 baud
 */
void uart_driver_init(void)
{
    Serial.begin(9600);
}

/**
 * @brief Print a formatted count value over UART
 * @param count Value to print
 */
void uart_driver_print_count(uint32_t count)
{
    Serial.print("COUNT: ");
    Serial.println(count);
}

/* ======================== Main Application ======================== */

static uint32_t blink_counter = 0;  /* Incrementing counter for serial output */

void setup(void)
{
    /* Initialize all modules */
    led_blink_init();
    uart_driver_init();
    
    /* Initial serial message */
    Serial.println("System started - LED Blink with Serial Count");
}

void loop(void)
{
    /* Blink LED with 500ms period (250ms on, 250ms off) */
    led_blink_toggle();
    
    /* Increment counter and print over serial */
    blink_counter++;
    uart_driver_print_count(blink_counter);
    
    /* Wait 250ms for half-period of 500ms blink */
    delay(250);
}