#include <Arduino.h>
/* FirmForge Boot Signature — AVR UART0 (TX=pin1, 9600) */
namespace {
struct _FirmForgeBoot {
    _FirmForgeBoot() {
        UBRR0H = (unsigned char)(103 >> 8);
        UBRR0L = (unsigned char)(103);
        UCSR0B = (1 << TXEN0);
        UCSR0C = (3 << UCSZ00);
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=4d5599d8\n";
        for (const char* p = sig; *p; p++) {
            while (!(UCSR0A & (1 << UDRE0))) { }
            UDR0 = (unsigned char)(*p);
        }
    }
} _firmforge_boot;
}

/*
 * led_blink.c - LED blinking application for Arduino Mega 2560
 * 
 * This module implements a simple LED blinking function using the
 * built-in LED on pin 13 (LED_BUILTIN).
 */

// ---------------------------------------------------------------------------
// Module: led_blink
// ---------------------------------------------------------------------------

/**
 * @brief Initialize the LED pin as an output.
 * 
 * This function configures the built-in LED pin (pin 13) as a digital output,
 * allowing it to be turned on and off.
 */
static void led_blink_init(void)
{
    // Set the built-in LED pin as output
    pinMode(LED_BUILTIN, OUTPUT);
    
    // Ensure LED starts in OFF state
    digitalWrite(LED_BUILTIN, LOW);
}

/**
 * @brief Toggle the built-in LED state.
 * 
 * This function reads the current state of the LED pin and toggles it.
 * If the LED is ON, it turns OFF; if OFF, it turns ON.
 */
static void led_blink_toggle(void)
{
    // Read current state of the LED pin
    uint8_t current_state = digitalRead(LED_BUILTIN);
    
    // Toggle the LED state
    if (current_state == HIGH) {
        digitalWrite(LED_BUILTIN, LOW);
    } else {
        digitalWrite(LED_BUILTIN, HIGH);
    }
}

/**
 * @brief Perform one blink cycle (ON for 500ms, OFF for 500ms).
 * 
 * This function turns the LED on, waits 500ms, turns it off, and waits 500ms.
 * It uses blocking delay() calls for simplicity.
 */
static void led_blink_cycle(void)
{
    // Turn LED ON
    digitalWrite(LED_BUILTIN, HIGH);
    // Wait for 500 milliseconds
    delay(500);
    
    // Turn LED OFF
    digitalWrite(LED_BUILTIN, LOW);
    // Wait for 500 milliseconds
    delay(500);
}

// ---------------------------------------------------------------------------
// Main application entry points (Arduino-style)
// ---------------------------------------------------------------------------

/**
 * @brief Arduino setup function.
 * 
 * This function is called once at startup. It initializes the serial
 * communication and the LED blink module.
 */
void setup(void)
{
    // Initialize serial communication at 9600 baud
    Serial.begin(9600);
    
    // Wait for serial port to connect (needed for some boards)
    // For Mega 2560, this is optional but good practice
    while (!Serial) {
        ; // Wait for serial connection
    }
    
    // Print startup message
    Serial.println("LED Blink Application Starting...");
    
    // Initialize the LED blink module
    led_blink_init();
    
    // Print initialization complete message
    Serial.println("Initialization Complete.");
}

/**
 * @brief Arduino main loop function.
 * 
 * This function runs repeatedly after setup(). It performs one LED blink
 * cycle (ON for 500ms, OFF for 500ms) and prints the state to serial.
 */
void loop(void)
{
    // Perform one blink cycle
    led_blink_cycle();
    
    // Print current state to serial for debugging
    uint8_t led_state = digitalRead(LED_BUILTIN);
    if (led_state == HIGH) {
        Serial.println("LED is ON");
    } else {
        Serial.println("LED is OFF");
    }
}