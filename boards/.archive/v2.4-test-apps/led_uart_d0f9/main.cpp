/*
 * main.c - LED Blink and UART Communication for Arduino UNO R3 (ATmega328P)
 * 
 * Features:
 * 1. LED_BUILTIN (pin 13) blinks at 200ms interval
 * 2. Serial prints "HELLO" at 9600 baud every 200ms
 * 
 * Compilation: avr-gcc -mmcu=atmega328p -DF_CPU=16000000UL -Os -o main.elf main.c
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
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=d0f9cfc6\n";
        for (const char* p = sig; *p; p++) {
            while (!(UCSR0A & (1 << UDRE0))) { }
            UDR0 = (unsigned char)(*p);
        }
    }
} _firmforge_boot;
}

/*============================================================================
 * Module: led_blink
 * Description: Controls the built-in LED with a 200ms blink period.
 * Dependencies: None
 *============================================================================*/

/**
 * @brief Initialize the LED pin as an output.
 *        Called once during system setup.
 */
void led_blink_init(void)
{
    pinMode(LED_BUILTIN, OUTPUT);
    digitalWrite(LED_BUILTIN, LOW);  /* Start with LED off */
}

/**
 * @brief Toggle the LED state. Call this at the desired blink rate.
 *        This function toggles the LED and returns immediately.
 */
void led_blink_toggle(void)
{
    static uint8_t led_state = LOW;
    
    led_state = (led_state == LOW) ? HIGH : LOW;
    digitalWrite(LED_BUILTIN, led_state);
}

/*============================================================================
 * Module: uart_driver
 * Description: Handles UART communication at 9600 baud.
 * Dependencies: None
 *============================================================================*/

/**
 * @brief Initialize UART at 9600 baud.
 *        Called once during system setup.
 */
void uart_driver_init(void)
{
    Serial.begin(9600);
    
    /* Wait a moment for serial to stabilize (optional, for robustness) */
    delay(50);
}

/**
 * @brief Send "HELLO" message over UART.
 *        This function blocks until the message is sent.
 */
void uart_driver_send_hello(void)
{
    Serial.println("HELLO");
}

/*============================================================================
 * Main Application
 *============================================================================*/

/**
 * @brief Arduino setup function.
 *        Initializes all modules and runs once at startup.
 */
void setup(void)
{
    /* Initialize modules */
    led_blink_init();
    uart_driver_init();
}

/**
 * @brief Arduino main loop.
 *        Runs repeatedly: blinks LED and sends "HELLO" every 200ms.
 */
void loop(void)
{
    /* Toggle LED state (200ms period = 100ms on, 100ms off) */
    led_blink_toggle();
    
    /* Send "HELLO" over serial */
    uart_driver_send_hello();
    
    /* Wait 200ms before next iteration */
    delay(200);
}