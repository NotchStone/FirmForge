/*
 * main.c - LED Blink and UART Communication for Arduino UNO R3 (ATmega328P)
 * 
 * Features:
 * 1. LED_BUILTIN (pin 13) blinks at 200ms interval
 * 2. Serial prints "HELLO" at 9600 baud every 200ms
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
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=648f3843\n";
        for (const char* p = sig; *p; p++) {
            while (!(UCSR0A & (1 << UDRE0))) { }
            UDR0 = (unsigned char)(*p);
        }
    }
} _firmforge_boot;
}

/*============================================================================
 * Module: led_blink
 * Description: Controls the built-in LED blinking at 200ms interval
 * Dependencies: None
 *============================================================================*/

/**
 * @brief Initialize the LED pin as output
 */
static void led_blink_init(void)
{
    pinMode(LED_BUILTIN, OUTPUT);
    digitalWrite(LED_BUILTIN, LOW);  // Start with LED off
}

/**
 * @brief Toggle the LED state
 *        Called every 200ms to create blinking effect
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
}

/**
 * @brief Send "HELLO" message over UART
 *        Called every 200ms to output the message
 */
static void uart_driver_send_hello(void)
{
    Serial.println("HELLO");
}

/*============================================================================
 * Main Application
 *============================================================================*/

/**
 * @brief Arduino setup function
 *        Initializes all modules once at startup
 */
void setup(void)
{
    /* Initialize LED blink module */
    led_blink_init();
    
    /* Initialize UART communication */
    uart_driver_init();
}

/**
 * @brief Arduino main loop
 *        Runs continuously, executing tasks at 200ms intervals
 * 
 * Scheduling: Simple auto-scheduling using delay() for 200ms period
 * Note: delay() blocks CPU - for production use millis() for non-blocking
 */
void loop(void)
{
    /* Update LED state (toggle) */
    led_blink_update();
    
    /* Send HELLO message over serial */
    uart_driver_send_hello();
    
    /* Wait for 200ms before next iteration */
    delay(200);
}