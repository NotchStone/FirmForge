/*
 * main.c - LED Blink and UART Communication for Arduino UNO R3 (ATmega328P)
 * 
 * Features:
 * 1. LED_BUILTIN (pin 13) blinks at 500ms interval
 * 2. Serial communication at 9600 baud, prints status message
 * 
 * F_CPU: 16MHz
 * Flash: 256KB, SRAM: 8KB
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
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=c22a0688\n";
        for (const char* p = sig; *p; p++) {
            while (!(UCSR0A & (1 << UDRE0))) { }
            UDR0 = (unsigned char)(*p);
        }
    }
} _firmforge_boot;
}

/*============================================================================
 * Module: led_blink
 * Description: Controls the built-in LED blinking at 500ms interval
 * Dependencies: None
 *============================================================================*/

/**
 * @brief Initialize the LED pin as output
 */
void led_blink_init(void)
{
    pinMode(LED_BUILTIN, OUTPUT);
    digitalWrite(LED_BUILTIN, LOW);  /* Start with LED off */
}

/**
 * @brief Toggle the LED state with 500ms delay
 * 
 * This function blocks for 500ms using delay().
 * For non-blocking operation, consider using millis() based timing.
 */
void led_blink_update(void)
{
    digitalWrite(LED_BUILTIN, HIGH);  /* Turn LED on */
    delay(500);                        /* Wait 500ms */

    digitalWrite(LED_BUILTIN, LOW);   /* Turn LED off */
    delay(500);                        /* Wait 500ms */
}

/*============================================================================
 * Module: uart_driver
 * Description: Handles UART serial communication at 9600 baud
 * Dependencies: None
 *============================================================================*/

/**
 * @brief Initialize UART serial communication
 * 
 * Configures serial port at 9600 baud rate.
 * Note: Uses Arduino Serial API which handles USART registers internally.
 */
void uart_driver_init(void)
{
    Serial.begin(9600);
    
    /* Wait for serial port to initialize (optional, for USB-serial adapters) */
    while (!Serial) {
        ;  /* Wait for serial connection (needed for some boards) */
    }
}

/**
 * @brief Send a status message over UART
 * 
 * Prints a simple message to indicate the system is running.
 */
void uart_driver_send_status(void)
{
    Serial.println("System OK - LED Blinking at 500ms");
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
    
    /* Send initial status message */
    uart_driver_send_status();
}

/**
 * @brief Arduino loop function - runs repeatedly
 * 
 * Main application loop:
 * - Blinks the built-in LED at 500ms interval
 * - Serial communication is handled by the blink cycle
 */
void loop(void)
{
    /* Update LED blink state (blocking delay inside) */
    led_blink_update();
}