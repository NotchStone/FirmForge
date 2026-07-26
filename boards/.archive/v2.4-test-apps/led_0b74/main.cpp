#include <Arduino.h>
/* FirmForge Boot Signature — AVR UART0 (TX=pin1, 9600) */
namespace {
struct _FirmForgeBoot {
    _FirmForgeBoot() {
        UBRR0H = (unsigned char)(103 >> 8);
        UBRR0L = (unsigned char)(103);
        UCSR0B = (1 << TXEN0);
        UCSR0C = (3 << UCSZ00);
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=0b74dba8\n";
        for (const char* p = sig; *p; p++) {
            while (!(UCSR0A & (1 << UDRE0))) { }
            UDR0 = (unsigned char)(*p);
        }
    }
} _firmforge_boot;
}

/*
 * led_blink.c - LED 500ms blink on pin 13 (LED_BUILTIN)
 * 
 * This module implements a simple LED blinking task.
 * The LED toggles every 500ms using blocking delay.
 */

// ---------------------------------------------------------------------------
// Module: led_blink
// ---------------------------------------------------------------------------

/**
 * @brief Initialize the LED pin as output.
 * 
 * This function sets the built-in LED pin (Arduino pin 13) to OUTPUT mode.
 * It should be called once during setup.
 */
void led_blink_init(void)
{
    pinMode(LED_BUILTIN, OUTPUT);
}

/**
 * @brief Toggle the LED state with a 500ms delay.
 * 
 * This function toggles the built-in LED and waits for 500ms.
 * It is intended to be called repeatedly in the main loop.
 */
void led_blink_update(void)
{
    digitalWrite(LED_BUILTIN, HIGH);
    delay(500);
    digitalWrite(LED_BUILTIN, LOW);
    delay(500);
}

// ---------------------------------------------------------------------------
// Main Arduino entry points
// ---------------------------------------------------------------------------

/**
 * @brief Arduino setup function.
 * 
 * Initializes the LED blink module.
 * Called once at startup.
 */
void setup(void)
{
    led_blink_init();
}

/**
 * @brief Arduino main loop.
 * 
 * Continuously toggles the LED with a 500ms period.
 */
void loop(void)
{
    led_blink_update();
}