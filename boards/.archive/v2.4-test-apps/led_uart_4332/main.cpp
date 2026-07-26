/*
 * main.c - LED blink and UART communication for Arduino UNO R3 (ATmega328P)
 * 
 * Features:
 * 1. LED_BUILTIN (pin 13) blinks with 200ms period
 * 2. Serial prints "HELLO" at 9600 baud every 2 seconds
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
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=433271d7\n";
        for (const char* p = sig; *p; p++) {
            while (!(UCSR0A & (1 << UDRE0))) { }
            UDR0 = (unsigned char)(*p);
        }
    }
} _firmforge_boot;
}

/* ========================================================================== */
/* Module: led_blink                                                          */
/* Description: Controls the built-in LED with a 200ms blink period           */
/* File: apps/task/led_blink.c                                                */
/* ========================================================================== */

/**
 * @brief Initialize the LED pin as output
 */
void led_blink_init(void)
{
    pinMode(LED_BUILTIN, OUTPUT);
    digitalWrite(LED_BUILTIN, LOW);
}

/**
 * @brief Toggle the LED state with 200ms delay
 * 
 * This function blocks for 200ms while toggling the LED.
 * For non-blocking operation, consider using millis() based timing.
 */
void led_blink_update(void)
{
    digitalWrite(LED_BUILTIN, HIGH);
    delay(100);  /* 100ms on */
    digitalWrite(LED_BUILTIN, LOW);
    delay(100);  /* 100ms off */
}

/* ========================================================================== */
/* Module: uart_driver                                                        */
/* Description: Handles UART communication at 9600 baud                       */
/* File: apps/task/uart_driver.c                                              */
/* ========================================================================== */

/* Timing constants for serial output */
#define SERIAL_BAUD_RATE    9600UL
#define SERIAL_INTERVAL_MS  2000UL

/* Last time "HELLO" was printed (in milliseconds) */
static unsigned long last_serial_time = 0;

/**
 * @brief Initialize UART at 9600 baud
 */
void uart_driver_init(void)
{
    Serial.begin(SERIAL_BAUD_RATE);
}

/**
 * @brief Print "HELLO" every 2 seconds
 * 
 * Uses millis() for non-blocking timing.
 */
void uart_driver_update(void)
{
    unsigned long current_time = millis();
    
    /* Check if 2 seconds have elapsed since last print */
    if (current_time - last_serial_time >= SERIAL_INTERVAL_MS)
    {
        Serial.println("HELLO");
        last_serial_time = current_time;
    }
}

/* ========================================================================== */
/* Main application                                                           */
/* ========================================================================== */

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
 * Executes all module update functions in sequence:
 * 1. Update LED blink state
 * 2. Update serial output
 */
void loop(void)
{
    /* Update LED blink (200ms period) */
    led_blink_update();
    
    /* Update serial output (every 2 seconds) */
    uart_driver_update();
}