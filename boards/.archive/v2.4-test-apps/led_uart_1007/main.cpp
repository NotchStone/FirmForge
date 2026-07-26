#include <Arduino.h>
/* FirmForge Boot Signature — AVR UART0 (TX=pin1, 9600) */
namespace {
struct _FirmForgeBoot {
    _FirmForgeBoot() {
        UBRR0H = (unsigned char)(103 >> 8);
        UBRR0L = (unsigned char)(103);
        UCSR0B = (1 << TXEN0);
        UCSR0C = (3 << UCSZ00);
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=1007fab6\n";
        for (const char* p = sig; *p; p++) {
            while (!(UCSR0A & (1 << UDRE0))) { }
            UDR0 = (unsigned char)(*p);
        }
    }
} _firmforge_boot;
}

/*
 * main.c - LED blink and UART communication for Arduino UNO R3 (ATmega328P)
 * 
 * Features:
 * 1. LED_BUILTIN (pin 13) blinks with 500ms period
 * 2. Serial communication at 9600 baud, prints status message
 */

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Blink interval in milliseconds (500ms = 0.5s) */
#define BLINK_INTERVAL_MS  500u

/** Serial baud rate */
#define SERIAL_BAUD        9600ul

// ---------------------------------------------------------------------------
// Module: led_blink
// ---------------------------------------------------------------------------

/**
 * @brief Initialize the built-in LED pin as output.
 */
static void led_blink_init(void)
{
    pinMode(LED_BUILTIN, OUTPUT);
    digitalWrite(LED_BUILTIN, LOW);
}

/**
 * @brief Toggle the built-in LED state.
 */
static void led_blink_toggle(void)
{
    digitalWrite(LED_BUILTIN, !digitalRead(LED_BUILTIN));
}

// ---------------------------------------------------------------------------
// Module: uart_driver
// ---------------------------------------------------------------------------

/**
 * @brief Initialize UART serial communication at the configured baud rate.
 */
static void uart_driver_init(void)
{
    Serial.begin(SERIAL_BAUD);
}

/**
 * @brief Send a status message over UART.
 */
static void uart_driver_send_status(void)
{
    Serial.println("OK");
}

// ---------------------------------------------------------------------------
// Arduino setup() and loop()
// ---------------------------------------------------------------------------

/**
 * @brief Arduino setup function.
 * 
 * Initializes all modules:
 * - LED blink module (pin mode)
 * - UART driver module (serial begin)
 * 
 * Sends initial status message.
 */
void setup(void)
{
    led_blink_init();
    uart_driver_init();

    // Send initial status message
    uart_driver_send_status();
}

/**
 * @brief Arduino main loop function.
 * 
 * Blinks the built-in LED every BLINK_INTERVAL_MS milliseconds.
 * Uses blocking delay for simplicity (single-task application).
 */
void loop(void)
{
    led_blink_toggle();
    delay(BLINK_INTERVAL_MS);
}