/*
 * main.c - Arduino UNO R3 (ATmega328P) firmware
 * 
 * Features:
 * 1. LED blinking at 200ms interval on built-in LED (pin 13)
 * 2. Serial communication at 9600 baud, printing "HELLO" periodically
 *
 * Compilation: avr-gcc -mmcu=atmega328p -DF_CPU=16000000UL -Os -o main.elf main.c
 * Programming: avrdude -c arduino -p m328p -P /dev/ttyACM0 -U flash:w:main.elf
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
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=33dbd863\n";
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
 * @brief Toggle the LED state
 *        Called every 200ms to create a blinking effect
 */
static void led_blink_update(void)
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
static void uart_driver_init(void)
{
    Serial.begin(9600);
    
    /* Wait for serial port to stabilize (optional, for USB-serial adapters) */
    delay(100);
}

/**
 * @brief Send "HELLO" message over UART
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
 * - LED blinking subsystem
 * - UART communication subsystem
 */
void setup(void)
{
    /* Initialize all functional modules */
    led_blink_init();
    uart_driver_init();
}

/**
 * @brief Arduino main loop - runs continuously
 * 
 * Implements a 200ms periodic task schedule:
 * - Toggle LED state
 * - Send "HELLO" over serial
 * 
 * Uses blocking delay for simplicity (200ms is short enough for this demo).
 * For more complex applications, consider using millis() for non-blocking timing.
 */
void loop(void)
{
    /* Update LED blink state (toggle every 200ms) */
    led_blink_update();
    
    /* Send HELLO message over UART */
    uart_driver_send_hello();
    
    /* Wait 200ms before next iteration */
    delay(200);
}