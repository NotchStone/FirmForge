/*
 * main.c - Arduino UNO R3 (ATmega328P) LED blink and UART communication
 * 
 * Features:
 * 1. LED_BUILTIN (pin 13) blinks with 200ms period
 * 2. Serial prints "HELLO" at 9600 baud
 * 
 * Compilation: avr-gcc -mmcu=atmega328p -DF_CPU=16000000UL -Os -o main.elf main.c
 * 
 * Hardware: Arduino UNO R3, ATmega328P @ 16MHz
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
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=85c95c33\n";
        for (const char* p = sig; *p; p++) {
            while (!(UCSR0A & (1 << UDRE0))) { }
            UDR0 = (unsigned char)(*p);
        }
    }
} _firmforge_boot;
}

/*============================================================================
 * Module: led_blink
 * Description: Controls the built-in LED with a 200ms blink period
 * Dependencies: None
 *============================================================================*/

/**
 * @brief Initialize the LED pin as output
 */
static void led_blink_init(void)
{
    pinMode(LED_BUILTIN, OUTPUT);
    digitalWrite(LED_BUILTIN, LOW);  /* Start with LED off */
}

/**
 * @brief Toggle the LED state with 200ms delay
 * 
 * This function blocks for 200ms. For non-blocking operation,
 * consider using millis() based timing.
 */
static void led_blink_update(void)
{
    digitalWrite(LED_BUILTIN, HIGH);  /* Turn LED on */
    delay(100);                       /* Wait 100ms */
    digitalWrite(LED_BUILTIN, LOW);   /* Turn LED off */
    delay(100);                       /* Wait 100ms */
}

/*============================================================================
 * Module: uart_driver
 * Description: UART communication at 9600 baud, prints "HELLO" periodically
 * Dependencies: None
 *============================================================================*/

/**
 * @brief Initialize UART at 9600 baud
 */
static void uart_driver_init(void)
{
    Serial.begin(9600);
    /* Allow time for serial monitor to connect */
    delay(100);
}

/**
 * @brief Print "HELLO" message over UART
 * 
 * Prints the message once per call. Caller controls timing.
 */
static void uart_driver_send_hello(void)
{
    Serial.println("HELLO");
}

/*============================================================================
 * Main application
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
    /* Initialize all modules */
    led_blink_init();
    uart_driver_init();
}

/**
 * @brief Arduino main loop - runs repeatedly
 * 
 * Performs:
 * 1. Blink LED with 200ms period (100ms on, 100ms off)
 * 2. Send "HELLO" over serial each cycle
 * 
 * Total cycle time: ~200ms (100ms on + 100ms off)
 */
void loop(void)
{
    /* Update LED blink state */
    led_blink_update();
    
    /* Send HELLO message over serial */
    uart_driver_send_hello();
}