/*
 * main.c - LED Blink and UART Communication for Arduino UNO R3 (ATmega328P)
 * 
 * Features:
 * 1. LED_BUILTIN (pin 13) blinks at 500ms interval
 * 2. Serial communication at 9600 baud, prints status message
 * 
 * F_CPU: 16MHz
 * Compiler: avr-gcc with Arduino core
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
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=de210177\n";
        for (const char* p = sig; *p; p++) {
            while (!(UCSR0A & (1 << UDRE0))) { }
            UDR0 = (unsigned char)(*p);
        }
    }
} _firmforge_boot;
}

/*============================================================================
 * Module: led_blink
 * Description: Controls the built-in LED with a 500ms blink pattern
 * Dependencies: None
 *============================================================================*/

/**
 * @brief Initialize the LED pin as output
 */
void led_blink_init(void)
{
    pinMode(LED_BUILTIN, OUTPUT);
}

/**
 * @brief Toggle the LED state with 500ms delay
 * 
 * This function toggles the built-in LED and waits for 500ms.
 * It is called repeatedly from the main loop.
 */
void led_blink_update(void)
{
    static uint8_t led_state = LOW;
    
    /* Toggle LED state */
    led_state = (led_state == LOW) ? HIGH : LOW;
    digitalWrite(LED_BUILTIN, led_state);
    
    /* Wait for 500ms */
    delay(500);
}

/*============================================================================
 * Module: uart_driver
 * Description: UART communication at 9600 baud
 * Dependencies: None
 *============================================================================*/

/**
 * @brief Initialize UART at 9600 baud
 */
void uart_driver_init(void)
{
    Serial.begin(9600);
}

/**
 * @brief Send a status message over UART
 * 
 * Prints "OK" message to indicate system is running.
 */
void uart_driver_send_status(void)
{
    static unsigned long last_print = 0;
    unsigned long current_time = millis();
    
    /* Print status every 1000ms (1 second) */
    if (current_time - last_print >= 1000)
    {
        Serial.println("OK");
        last_print = current_time;
    }
}

/*============================================================================
 * Main Arduino Functions
 *============================================================================*/

/**
 * @brief Arduino setup function
 * 
 * Initializes all modules:
 * - LED blink module
 * - UART communication module
 */
void setup(void)
{
    /* Initialize LED blink module */
    led_blink_init();
    
    /* Initialize UART communication */
    uart_driver_init();
    
    /* Print initial message */
    Serial.println("System started");
}

/**
 * @brief Arduino main loop
 * 
 * Runs continuously:
 * - Updates LED blink state
 * - Sends UART status message
 */
void loop(void)
{
    /* Update LED blink (500ms toggle) */
    led_blink_update();
    
    /* Send UART status message */
    uart_driver_send_status();
}