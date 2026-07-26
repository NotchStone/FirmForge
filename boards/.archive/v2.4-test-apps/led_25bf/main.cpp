#include <Arduino.h>
/* FirmForge Boot Signature — AVR UART0 (TX=pin1, 9600) */
namespace {
struct _FirmForgeBoot {
    _FirmForgeBoot() {
        UBRR0H = (unsigned char)(103 >> 8);
        UBRR0L = (unsigned char)(103);
        UCSR0B = (1 << TXEN0);
        UCSR0C = (3 << UCSZ00);
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=25bfa6e9\n";
        for (const char* p = sig; *p; p++) {
            while (!(UCSR0A & (1 << UDRE0))) { }
            UDR0 = (unsigned char)(*p);
        }
    }
} _firmforge_boot;
}

/*
 * led_blink.c - LED Blink Task
 * 
 * Blinks the built-in LED on Arduino UNO R3 (ATmega328P) at 500ms intervals.
 * 
 * Hardware:
 *   - LED_BUILTIN (Pin 13) on Arduino UNO R3
 * 
 * Timing:
 *   - ON for 500ms
 *   - OFF for 500ms
 */

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Blink interval in milliseconds */
static const uint16_t BLINK_INTERVAL_MS = 500;

// ---------------------------------------------------------------------------
// Module: led_blink
// ---------------------------------------------------------------------------

/**
 * @brief Initialize the LED blink module.
 * 
 * Configures the built-in LED pin as an output.
 */
static void led_blink_init(void)
{
    pinMode(LED_BUILTIN, OUTPUT);
    digitalWrite(LED_BUILTIN, LOW);
}

/**
 * @brief Update the LED blink state.
 * 
 * Toggles the built-in LED state. This function should be called
 * periodically from the main loop.
 */
static void led_blink_update(void)
{
    static uint8_t led_state = LOW;

    // Toggle the LED state
    led_state = (led_state == HIGH) ? LOW : HIGH;
    digitalWrite(LED_BUILTIN, led_state);
}

// ---------------------------------------------------------------------------
// Arduino Entry Points
// ---------------------------------------------------------------------------

/**
 * @brief Arduino setup function.
 * 
 * Called once at startup. Initializes all modules.
 */
void setup(void)
{
    // Initialize the LED blink module
    led_blink_init();
}

/**
 * @brief Arduino main loop function.
 * 
 * Called repeatedly after setup(). Updates the LED blink state
 * at the configured interval.
 */
void loop(void)
{
    led_blink_update();
    delay(BLINK_INTERVAL_MS);
}