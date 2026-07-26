/*
 * main.c - Arduino UNO R3 (ATmega328P) firmware
 * 
 * Features:
 * 1. LED blinking at 200ms interval
 * 2. UART communication at 9600 baud
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
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=1c444286\n";
        for (const char* p = sig; *p; p++) {
            while (!(UCSR0A & (1 << UDRE0))) { }
            UDR0 = (unsigned char)(*p);
        }
    }
} _firmforge_boot;
}

/*============================================================================
 * Module: led_blink
 * Description: Controls the built-in LED with 200ms on/off interval
 *============================================================================*/

/**
 * @brief Initialize the LED pin as output
 */
static void led_blink_init(void)
{
    pinMode(LED_BUILTIN, OUTPUT);
    digitalWrite(LED_BUILTIN, LOW);
}

/**
 * @brief Toggle the LED state with 200ms delay
 * 
 * This function blocks for 200ms while the LED is on,
 * then blocks for another 200ms while the LED is off.
 */
static void led_blink_update(void)
{
    digitalWrite(LED_BUILTIN, HIGH);
    delay(200);
    digitalWrite(LED_BUILTIN, LOW);
    delay(200);
}

/*============================================================================
 * Module: uart_driver
 * Description: Handles serial communication at 9600 baud
 *============================================================================*/

/**
 * @brief Initialize UART at 9600 baud
 */
static void uart_driver_init(void)
{
    Serial.begin(9600);
}

/**
 * @brief Send "HELLO" message over UART
 * 
 * Prints the message once per call.
 */
static void uart_driver_update(void)
{
    Serial.println("HELLO");
}

/*============================================================================
 * Main application
 *============================================================================*/

/**
 * @brief Arduino setup function
 * 
 * Initializes all modules:
 * - LED blinking module
 * - UART communication module
 */
void setup(void)
{
    led_blink_init();
    uart_driver_init();
}

/**
 * @brief Arduino main loop
 * 
 * Executes all tasks in sequence:
 * 1. Blink LED with 200ms interval
 * 2. Send "HELLO" over serial
 * 
 * The loop repeats indefinitely.
 */
void loop(void)
{
    led_blink_update();
    uart_driver_update();
}