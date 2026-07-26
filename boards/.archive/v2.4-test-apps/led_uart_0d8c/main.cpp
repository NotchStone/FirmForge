/*
 * main.c - LED Blink and UART Communication for Arduino UNO R3 (ATmega328P)
 * 
 * Features:
 * 1. LED_BUILTIN (pin 13) blinks with 200ms period
 * 2. Serial output "HELLO" at 9600 baud every 200ms
 * 
 * Compilation: avr-gcc -mmcu=atmega328p -DF_CPU=16000000UL -Os -o main.elf main.c
 * 
 * Hardware: Arduino UNO R3 (ATmega328P, 16MHz)
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
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=0d8c71e9\n";
        for (const char* p = sig; *p; p++) {
            while (!(UCSR0A & (1 << UDRE0))) { }
            UDR0 = (unsigned char)(*p);
        }
    }
} _firmforge_boot;
}

/*============================================================================
 * Module: led_blink
 * Description: Controls the built-in LED with 200ms blink period
 * Dependencies: None
 *============================================================================*/

/**
 * @brief Initialize the LED pin as output
 */
void led_blink_init(void)
{
    pinMode(LED_BUILTIN, OUTPUT);
    digitalWrite(LED_BUILTIN, LOW);  // Start with LED off
}

/**
 * @brief Toggle the LED state
 * Called every 200ms to create a blinking effect
 */
void led_blink_toggle(void)
{
    static uint8_t led_state = LOW;
    
    led_state = (led_state == LOW) ? HIGH : LOW;
    digitalWrite(LED_BUILTIN, led_state);
}

/*============================================================================
 * Module: uart_driver
 * Description: Handles UART communication at 9600 baud
 * Dependencies: None
 *============================================================================*/

/**
 * @brief Initialize UART at 9600 baud
 */
void uart_driver_init(void)
{
    Serial.begin(9600);
    
    /* Wait for serial port to initialize (optional, for stability) */
    delay(100);
}

/**
 * @brief Send "HELLO" message over UART
 */
void uart_driver_send_hello(void)
{
    Serial.println("HELLO");
}

/*============================================================================
 * Main Application
 *============================================================================*/

/**
 * @brief Arduino setup function - runs once at startup
 * 
 * Initializes all modules:
 * - LED blink module
 * - UART communication module
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
 * Main execution loop:
 * - Toggle LED every 200ms
 * - Send "HELLO" over serial every 200ms
 * 
 * Note: Both operations are synchronized with the same delay
 * for simplicity. For more complex timing, use millis() based
 * non-blocking approach.
 */
void loop(void)
{
    /* Toggle the LED state */
    led_blink_toggle();
    
    /* Send HELLO message over serial */
    uart_driver_send_hello();
    
    /* Wait 200ms before next iteration */
    delay(200);
}