#include <Arduino.h>
/* FirmForge Boot Signature — AVR UART0 (TX=pin1, 9600) */
namespace {
struct _FirmForgeBoot {
    _FirmForgeBoot() {
        UBRR0H = (unsigned char)(103 >> 8);
        UBRR0L = (unsigned char)(103);
        UCSR0B = (1 << TXEN0);
        UCSR0C = (3 << UCSZ00);
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=f72f0773\n";
        for (const char* p = sig; *p; p++) {
            while (!(UCSR0A & (1 << UDRE0))) { }
            UDR0 = (unsigned char)(*p);
        }
    }
} _firmforge_boot;
}

/*
 * led_blink.c - LED 500ms blink on pin 13
 * 
 * This module implements a simple LED blinking function.
 * The built-in LED (pin 13) toggles every 500ms.
 */

// ---------------------------------------------------------------------------
// Module: led_blink
// ---------------------------------------------------------------------------

/**
 * @brief Initialize the LED pin as output.
 * 
 * This function sets the LED_BUILTIN pin to OUTPUT mode,
 * allowing digitalWrite to control the LED state.
 */
void led_blink_init(void)
{
    pinMode(LED_BUILTIN, OUTPUT);
}

/**
 * @brief Toggle the LED state with a 500ms delay.
 * 
 * This function reads the current state of the LED pin,
 * inverts it, and writes the new state. A 500ms delay
 * is added to create a visible blinking effect.
 */
void led_blink_update(void)
{
    // Read current LED state
    int led_state = digitalRead(LED_BUILTIN);
    
    // Toggle the LED state
    digitalWrite(LED_BUILTIN, !led_state);
    
    // Wait 500ms before next toggle
    delay(500);
}

// ---------------------------------------------------------------------------
// Main entry point (Arduino style)
// ---------------------------------------------------------------------------

/**
 * @brief Arduino setup function.
 * 
 * This function is called once at startup.
 * It initializes the LED blink module.
 */
void setup(void)
{
    led_blink_init();
}

/**
 * @brief Arduino main loop function.
 * 
 * This function is called repeatedly.
 * It updates the LED blink state.
 */
void loop(void)
{
    led_blink_update();
}