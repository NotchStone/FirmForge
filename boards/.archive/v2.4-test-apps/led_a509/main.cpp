#include <Arduino.h>
/* FirmForge Boot Signature — AVR UART0 (TX=pin1, 9600) */
namespace {
struct _FirmForgeBoot {
    _FirmForgeBoot() {
        UBRR0H = (unsigned char)(103 >> 8);
        UBRR0L = (unsigned char)(103);
        UCSR0B = (1 << TXEN0);
        UCSR0C = (3 << UCSZ00);
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=a509bda6\n";
        for (const char* p = sig; *p; p++) {
            while (!(UCSR0A & (1 << UDRE0))) { }
            UDR0 = (unsigned char)(*p);
        }
    }
} _firmforge_boot;
}

/*
 * LED Blink Application
 * 
 * Blinks the built-in LED (pin 13) on Arduino UNO R3 at 500ms intervals.
 * 
 * Hardware:
 *   - MCU: ATmega328P (Arduino UNO R3)
 *   - LED_BUILTIN: Pin 13 (PORTB bit 7)
 * 
 * Timing:
 *   - ON time: 500ms
 *   - OFF time: 500ms
 *   - Period: 1000ms
 */

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** LED blink interval in milliseconds */
static const uint16_t BLINK_INTERVAL_MS = 500;

// ---------------------------------------------------------------------------
// Module: led_blink
// ---------------------------------------------------------------------------

/**
 * @brief Initializes the LED pin as an output.
 * 
 * This function must be called once during system setup to configure
 * the built-in LED pin for digital output.
 */
static void led_blink_init(void)
{
    pinMode(LED_BUILTIN, OUTPUT);
    digitalWrite(LED_BUILTIN, LOW);
}

/**
 * @brief Toggles the LED state.
 * 
 * Reads the current state of the LED pin and inverts it.
 * This provides a simple toggle without needing to track state.
 */
static void led_blink_toggle(void)
{
    uint8_t current_state = digitalRead(LED_BUILTIN);
    digitalWrite(LED_BUILTIN, !current_state);
}

/**
 * @brief Performs one blink cycle.
 * 
 * Toggles the LED and waits for the specified interval.
 * This is a blocking delay implementation suitable for simple blinking.
 */
static void led_blink_update(void)
{
    led_blink_toggle();
    delay(BLINK_INTERVAL_MS);
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
    led_blink_init();
}

/**
 * @brief Arduino main loop.
 * 
 * Called repeatedly. Executes the LED blink cycle.
 */
void loop(void)
{
    led_blink_update();
}