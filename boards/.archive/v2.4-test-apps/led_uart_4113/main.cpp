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
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=411301c0\n";
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
 * Dependencies: None
 * ========================================================================== */

/**
 * @brief Initialize LED pin as output
 */
void led_blink_init(void)
{
    pinMode(LED_BUILTIN, OUTPUT);
    digitalWrite(LED_BUILTIN, LOW);
}

/**
 * @brief Toggle LED state with 200ms delay
 * 
 * This function blocks for 200ms while toggling the LED.
 * For non-blocking operation, use millis() based timing.
 */
void led_blink_update(void)
{
    digitalWrite(LED_BUILTIN, HIGH);
    delay(200);
    digitalWrite(LED_BUILTIN, LOW);
    delay(200);
}

/* ==========================================================================
 * Module: uart_driver
 * Description: Handles serial communication at 9600 baud
 * Dependencies: None
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
 * Called every 2 seconds from main loop.
 */
void uart_driver_send_hello(void)
{
    Serial.println("HELLO");
}

/* ==========================================================================
 * Main application
 * ========================================================================== */

/**
 * @brief Timing variables for non-blocking 2-second interval
 */
static unsigned long last_hello_time = 0;
static const unsigned long hello_interval = 2000; /* 2 seconds in milliseconds */

/**
 * @brief Arduino setup function
 * 
 * Initializes all modules and runs once at startup.
 */
void setup(void)
{
    /* Initialize LED blink module */
    led_blink_init();
    
    /* Initialize UART communication */
    uart_driver_init();
    
    /* Record initial time for serial interval timing */
    last_hello_time = millis();
}

/**
 * @brief Arduino main loop
 * 
 * Runs continuously after setup():
 * - Blinks LED with 200ms interval
 * - Sends "HELLO" over serial every 2 seconds
 */
void loop(void)
{
    /* Update LED blink (blocking 200ms toggle) */
    led_blink_update();
    
    /* Check if 2 seconds have elapsed for serial message */
    unsigned long current_time = millis();
    if (current_time - last_hello_time >= hello_interval)
    {
        uart_driver_send_hello();
        last_hello_time = current_time;
    }
}