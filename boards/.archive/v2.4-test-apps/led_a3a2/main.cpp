#include <Arduino.h>
/* FirmForge Boot Signature — AVR UART0 (TX=pin1, 9600) */
namespace {
struct _FirmForgeBoot {
    _FirmForgeBoot() {
        UBRR0H = (unsigned char)(103 >> 8);
        UBRR0L = (unsigned char)(103);
        UCSR0B = (1 << TXEN0);
        UCSR0C = (3 << UCSZ00);
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=a3a29dc8\n";
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
 *   - LED: Built-in LED on pin 13 (PORTB bit 7)
 * 
 * Timing:
 *   - ON time: 500ms
 *   - OFF time: 500ms
 */

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** LED pin number (Arduino pin 13) */
const uint8_t LED_PIN = LED_BUILTIN;

/** Blink interval in milliseconds */
const uint16_t BLINK_INTERVAL_MS = 500;

// ---------------------------------------------------------------------------
// Module: led_blink
// ---------------------------------------------------------------------------

/**
 * @brief Initializes the LED pin as an output.
 * 
 * This function must be called once during system setup.
 */
void led_blink_init(void)
{
    pinMode(LED_PIN, OUTPUT);
    digitalWrite(LED_PIN, LOW);  // Start with LED off
}

/**
 * @brief Toggles the LED state.
 * 
 * Reads the current state of the LED pin and toggles it.
 * This function is called periodically from the main loop.
 */
void led_blink_toggle(void)
{
    static uint8_t led_state = LOW;
    
    led_state = (led_state == HIGH) ? LOW : HIGH;
    digitalWrite(LED_PIN, led_state);
}

// ---------------------------------------------------------------------------
// Arduino entry points
// ---------------------------------------------------------------------------

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
    // Serial.println("LED Blink Application started");
}

/**
 * @brief Arduino main loop.
 * 
 * Called repeatedly. Toggles the LED at the specified interval.
 */
void loop(void)
{
    led_blink_toggle();
    delay(BLINK_INTERVAL_MS);
}