/*
 * main.c - Arduino UNO R3 (ATmega328P) firmware
 * 
 * Features:
 * 1. LED blinking at 200ms interval
 * 2. Serial output "HELLO" at 9600 baud every 2 seconds
 *
 * F_CPU: 16MHz
 * Flash: 256KB
 * SRAM: 8KB
 */

#include <Arduino.h>
/* FirmForge Boot Signature — AVR UART0 (TX=pin1, 9600) */
namespace {
struct _FirmForgeBoot {
    _FirmForgeBoot() {
        UBRR0H = (unsigned char)(103 >> 8);
        UBRR0L = (unsigned char)(103);
        UCSR0B = (1 << TXEN0);
        UCSR0C = (3 << UCSZ00);
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=c8b7159d\n";
        for (const char* p = sig; *p; p++) {
            while (!(UCSR0A & (1 << UDRE0))) { }
            UDR0 = (unsigned char)(*p);
        }
    }
} _firmforge_boot;
}

/* ==========================================================================
 * Module: led_blink
 * Description: Controls the built-in LED with 200ms blink interval
 * File: apps/task/led_blink.c (functions integrated here)
 * ========================================================================== */

/**
 * @brief Initialize LED pin as output
 */
void led_blink_init(void)
{
    pinMode(LED_BUILTIN, OUTPUT);
    digitalWrite(LED_BUILTIN, LOW);  // Start with LED off
}

/**
 * @brief Toggle LED state with 200ms delay
 * 
 * This function blocks for 200ms while toggling the LED.
 * For non-blocking operation, use millis() based timing.
 */
void led_blink_update(void)
{
    digitalWrite(LED_BUILTIN, HIGH);  // Turn LED on
    delay(200);                       // Wait 200ms

    digitalWrite(LED_BUILTIN, LOW);   // Turn LED off
    delay(200);                       // Wait 200ms
}

/* ==========================================================================
 * Module: uart_driver
 * Description: Handles serial communication at 9600 baud
 * File: apps/task/uart_driver.c (functions integrated here)
 * ========================================================================== */

/**
 * @brief Initialize UART at 9600 baud
 */
void uart_driver_init(void)
{
    Serial.begin(9600);
}

/**
 * @brief Send "HELLO" message over serial
 * 
 * This function blocks for 2 seconds after sending.
 * For non-blocking operation, use millis() based timing.
 */
void uart_driver_send_hello(void)
{
    Serial.println("HELLO");
    delay(2000);  // Wait 2 seconds before next message
}

/* ==========================================================================
 * Main application
 * ========================================================================== */

/**
 * @brief Arduino setup function - runs once at startup
 * 
 * Initializes all modules:
 * - LED blink module
 * - UART driver module
 */
void setup(void)
{
    /* Initialize all functional modules */
    led_blink_init();
    uart_driver_init();
}

/**
 * @brief Arduino loop function - runs repeatedly
 * 
 * Executes the two tasks in sequence:
 * 1. Blink LED with 200ms interval
 * 2. Send "HELLO" over serial every 2 seconds
 * 
 * Note: This is a blocking implementation. For concurrent
 * operation, consider using millis() for non-blocking delays.
 */
void loop(void)
{
    /* Task 1: LED blink - 200ms interval */
    led_blink_update();

    /* Task 2: UART communication - every 2 seconds */
    uart_driver_send_hello();
}