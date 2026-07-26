/*
 * main.c - Arduino UNO R3 (ATmega328P) firmware
 * 
 * Features:
 * 1. LED blink on pin 13 (LED_BUILTIN) with 200ms period
 * 2. UART communication at 9600 baud, printing "HELLO" periodically
 *
 * Compilation: avr-gcc -mmcu=atmega328p -DF_CPU=16000000UL -Os -o main.elf main.c
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
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=2ecf078a\n";
        for (const char* p = sig; *p; p++) {
            while (!(UCSR0A & (1 << UDRE0))) { }
            UDR0 = (unsigned char)(*p);
        }
    }
} _firmforge_boot;
}

/*============================================================================
 * Module: led_blink
 * Description: Controls the built-in LED with a 200ms blink period.
 * Dependencies: None
 *============================================================================*/

/**
 * @brief Initialize the LED pin as an output.
 */
void led_blink_init(void)
{
    pinMode(LED_BUILTIN, OUTPUT);
    digitalWrite(LED_BUILTIN, LOW);  /* Start with LED off */
}

/**
 * @brief Toggle the LED state.
 *        Called periodically to achieve 200ms blink (100ms on, 100ms off).
 */
void led_blink_toggle(void)
{
    static uint8_t led_state = LOW;

    led_state = (led_state == LOW) ? HIGH : LOW;
    digitalWrite(LED_BUILTIN, led_state);
}

/*============================================================================
 * Module: uart_driver
 * Description: Handles UART communication at 9600 baud.
 * Dependencies: None
 *============================================================================*/

/**
 * @brief Initialize UART at 9600 baud.
 */
void uart_driver_init(void)
{
    Serial.begin(9600);
}

/**
 * @brief Send "HELLO" message over UART.
 */
void uart_driver_send_hello(void)
{
    Serial.println("HELLO");
}

/*============================================================================
 * Main application
 *============================================================================*/

/**
 * @brief Arduino setup function.
 *        Initializes all modules once at startup.
 */
void setup(void)
{
    led_blink_init();
    uart_driver_init();
}

/**
 * @brief Arduino main loop.
 *        Runs continuously after setup().
 *        Blinks LED every 200ms and prints "HELLO" each cycle.
 */
void loop(void)
{
    led_blink_toggle();
    uart_driver_send_hello();
    delay(200);  /* 200ms delay for both LED blink and serial output */
}