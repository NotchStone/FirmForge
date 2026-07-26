#include <Arduino.h>
/* FirmForge Boot Signature — AVR UART0 (TX=pin1, 9600) */
namespace {
struct _FirmForgeBoot {
    _FirmForgeBoot() {
        UBRR0H = (unsigned char)(103 >> 8);
        UBRR0L = (unsigned char)(103);
        UCSR0B = (1 << TXEN0);
        UCSR0C = (3 << UCSZ00);
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=c1e99798\n";
        for (const char* p = sig; *p; p++) {
            while (!(UCSR0A & (1 << UDRE0))) { }
            UDR0 = (unsigned char)(*p);
        }
    }
} _firmforge_boot;
}

// ============================================================================
// Module: LED Blink
// Description: Blinks the built-in LED on pin 13 with a 500ms period.
// ============================================================================

// ----------------------------------------------------------------------------
// Constants
// ----------------------------------------------------------------------------

/** LED pin number (Arduino pin 13, PB7 on ATmega328P) */
static const uint8_t LED_PIN = LED_BUILTIN;

/** Blink interval in milliseconds (500ms on, 500ms off = 1s period) */
static const uint16_t BLINK_INTERVAL_MS = 500;

// ----------------------------------------------------------------------------
// Module: led_blink
// ----------------------------------------------------------------------------

/**
 * @brief Initializes the LED pin as an output.
 *
 * This function must be called once during setup() to configure the
 * GPIO direction for the built-in LED pin.
 */
static void led_blink_init(void)
{
    pinMode(LED_PIN, OUTPUT);
    digitalWrite(LED_PIN, LOW);  // start with LED off
}

/**
 * @brief Toggles the LED state.
 *
 * Reads the current state of the LED pin and writes the opposite value.
 * This produces a 50% duty cycle square wave on the LED.
 */
static void led_blink_toggle(void)
{
    uint8_t current_state = digitalRead(LED_PIN);
    digitalWrite(LED_PIN, (current_state == HIGH) ? LOW : HIGH);
}

/**
 * @brief Performs one blink cycle (blocking delay).
 *
 * Toggles the LED and waits for the specified interval.
 * Note: This function blocks the CPU during the delay.
 * For non-blocking operation, use millis() instead.
 */
static void led_blink_update(void)
{
    led_blink_toggle();
    delay(BLINK_INTERVAL_MS);
}

// ============================================================================
// Arduino Entry Points
// ============================================================================

/**
 * @brief Arduino setup function.
 *
 * Called once at startup. Initializes all modules.
 */
void setup(void)
{
    // Initialize LED blink module
    led_blink_init();

    // Optional: Initialize serial for debugging (uncomment if needed)
    // Serial.begin(9600);
    // Serial.println("LED Blink started");
}

/**
 * @brief Arduino main loop function.
 *
 * Called repeatedly after setup(). Runs the LED blink cycle.
 */
void loop(void)
{
    led_blink_update();
}