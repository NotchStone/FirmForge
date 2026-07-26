#include <Arduino.h>
/* FirmForge Boot Signature — AVR UART0 (TX=pin1, 9600) */
namespace {
struct _FirmForgeBoot {
    _FirmForgeBoot() {
        UBRR0H = (unsigned char)(103 >> 8);
        UBRR0L = (unsigned char)(103);
        UCSR0B = (1 << TXEN0);
        UCSR0C = (3 << UCSZ00);
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=399776a2\n";
        for (const char* p = sig; *p; p++) {
            while (!(UCSR0A & (1 << UDRE0))) { }
            UDR0 = (unsigned char)(*p);
        }
    }
} _firmforge_boot;
}

/*
 * led_blink.c - LED 500ms slow blink on pin 13
 * 
 * This module implements a simple LED blinking functionality.
 * The built-in LED (pin 13) toggles every 500ms.
 */

// Pin definitions
#define LED_PIN         13      // Built-in LED pin on Arduino UNO R3
#define BLINK_INTERVAL  500     // Blink interval in milliseconds

// Function prototypes
void led_blink_init(void);
void led_blink_update(void);

/*
 * Initialize the LED pin as output
 */
void led_blink_init(void)
{
    pinMode(LED_PIN, OUTPUT);
    digitalWrite(LED_PIN, LOW);  // Start with LED off
}

/*
 * Toggle the LED state with 500ms delay
 * Note: This uses blocking delay for simplicity.
 * For non-blocking operation, consider using millis().
 */
void led_blink_update(void)
{
    digitalWrite(LED_PIN, HIGH);  // Turn LED on
    delay(BLINK_INTERVAL);        // Wait 500ms
    
    digitalWrite(LED_PIN, LOW);   // Turn LED off
    delay(BLINK_INTERVAL);        // Wait 500ms
}

/*
 * Arduino setup function - runs once at startup
 */
void setup(void)
{
    // Initialize serial communication (optional, for debugging)
    Serial.begin(9600);
    Serial.println("LED Blink Demo Starting...");
    
    // Initialize LED blink module
    led_blink_init();
}

/*
 * Arduino main loop - runs repeatedly
 */
void loop(void)
{
    led_blink_update();
}