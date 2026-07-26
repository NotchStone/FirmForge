#include <Arduino.h>
/* FirmForge Boot Signature — AVR UART0 (TX=pin1, 9600) */
namespace {
struct _FirmForgeBoot {
    _FirmForgeBoot() {
        UBRR0H = (unsigned char)(103 >> 8);
        UBRR0L = (unsigned char)(103);
        UCSR0B = (1 << TXEN0);
        UCSR0C = (3 << UCSZ00);
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=932000f1\n";
        for (const char* p = sig; *p; p++) {
            while (!(UCSR0A & (1 << UDRE0))) { }
            UDR0 = (unsigned char)(*p);
        }
    }
} _firmforge_boot;
}

/*
 * led_blink.c - LED blinking application for Arduino UNO R3
 * 
 * This module implements a simple LED blinking functionality using the
 * built-in LED on pin 13 (LED_BUILTIN). The LED toggles every 500ms.
 */

// ---------------------------------------------------------------------------
// Module: led_blink
// ---------------------------------------------------------------------------

/**
 * @brief Blink interval in milliseconds.
 * 
 * The LED will be on for this duration and off for this duration,
 * resulting in a complete blink cycle of 2 * BLINK_INTERVAL_MS.
 */
#define BLINK_INTERVAL_MS 500u

/**
 * @brief Initialize the LED pin as an output.
 * 
 * This function must be called once during setup to configure the
 * built-in LED pin for digital output.
 */
static void led_blink_init(void)
{
    pinMode(LED_BUILTIN, OUTPUT);
    digitalWrite(LED_BUILTIN, LOW);  // Start with LED off
}

/**
 * @brief Perform one blink cycle.
 * 
 * Toggles the LED state. This function is intended to be called
 * repeatedly from the main loop to achieve continuous blinking.
 */
static void led_blink_toggle(void)
{
    static uint8_t led_state = LOW;

    // Toggle the LED state
    led_state = (led_state == HIGH) ? LOW : HIGH;
    digitalWrite(LED_BUILTIN, led_state);
}

// ---------------------------------------------------------------------------
// Main application
// ---------------------------------------------------------------------------

/**
 * @brief Arduino setup function.
 * 
 * Initializes serial communication and the LED blink module.
 * Called once at startup.
 */
void setup(void)
{
    // Initialize serial communication at 9600 baud
    Serial.begin(9600);
    Serial.println("LED Blink Application Started");

    // Initialize the LED blink module
    led_blink_init();
}

/**
 * @brief Arduino main loop function.
 * 
 * Continuously toggles the LED with a fixed delay.
 * Called repeatedly after setup() completes.
 */
void loop(void)
{
    // Toggle the LED state
    led_blink_toggle();

    // Wait for the blink interval
    delay(BLINK_INTERVAL_MS);
}