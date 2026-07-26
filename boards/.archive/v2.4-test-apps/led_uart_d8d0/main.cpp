/*
 * main.c - LED Blink and UART Communication for Arduino UNO R3 (ATmega328P)
 * 
 * Features:
 * 1. LED_BUILTIN (pin 13) blinks with 200ms period
 * 2. Serial communication at 9600 baud, prints "HELLO" periodically
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
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=d8d03e6a\n";
        for (const char* p = sig; *p; p++) {
            while (!(UCSR0A & (1 << UDRE0))) { }
            UDR0 = (unsigned char)(*p);
        }
    }
} _firmforge_boot;
}

/* ========================================================================== */
/* Module: led_blink                                                          */
/* File: apps/task/led_blink.c                                                */
/* Description: Controls the built-in LED with a 200ms blink period           */
/* ========================================================================== */

/* LED blink timing constants (in milliseconds) */
#define LED_BLINK_INTERVAL_MS  200u

/* Last time the LED state was toggled (for non-blocking timing) */
static unsigned long last_led_toggle_ms = 0u;

/* Current state of the LED (HIGH = on, LOW = off) */
static uint8_t led_state = LOW;

/**
 * @brief Initialize the LED pin as an output
 */
static void led_blink_init(void)
{
    pinMode(LED_BUILTIN, OUTPUT);
    digitalWrite(LED_BUILTIN, LOW);
}

/**
 * @brief Update the LED state based on elapsed time (non-blocking)
 * 
 * This function should be called repeatedly from the main loop.
 * It toggles the LED every LED_BLINK_INTERVAL_MS milliseconds.
 */
static void led_blink_update(void)
{
    unsigned long current_ms = millis();
    
    if ((current_ms - last_led_toggle_ms) >= LED_BLINK_INTERVAL_MS)
    {
        /* Toggle the LED state */
        led_state = (led_state == HIGH) ? LOW : HIGH;
        digitalWrite(LED_BUILTIN, led_state);
        
        /* Update the last toggle timestamp */
        last_led_toggle_ms = current_ms;
    }
}

/* ========================================================================== */
/* Module: uart_driver                                                        */
/* File: apps/task/uart_driver.c                                              */
/* Description: Handles UART communication at 9600 baud                       */
/* ========================================================================== */

/* UART baud rate */
#define UART_BAUD_RATE  9600u

/* Interval between "HELLO" messages (in milliseconds) */
#define UART_HELLO_INTERVAL_MS  1000u

/* Last time a "HELLO" message was sent */
static unsigned long last_hello_ms = 0u;

/**
 * @brief Initialize the UART interface
 */
static void uart_driver_init(void)
{
    Serial.begin(UART_BAUD_RATE);
}

/**
 * @brief Send "HELLO" message periodically (non-blocking)
 * 
 * This function should be called repeatedly from the main loop.
 * It prints "HELLO" every UART_HELLO_INTERVAL_MS milliseconds.
 */
static void uart_driver_update(void)
{
    unsigned long current_ms = millis();
    
    if ((current_ms - last_hello_ms) >= UART_HELLO_INTERVAL_MS)
    {
        Serial.println("HELLO");
        last_hello_ms = current_ms;
    }
}

/* ========================================================================== */
/* Main Application - setup() and loop()                                      */
/* ========================================================================== */

/**
 * @brief Arduino setup function - runs once at startup
 * 
 * Initializes all modules and sets up the system.
 */
void setup(void)
{
    /* Initialize modules */
    led_blink_init();
    uart_driver_init();
    
    /* Small delay to allow serial monitor to connect */
    delay(100u);
}

/**
 * @brief Arduino loop function - runs repeatedly
 * 
 * Updates all modules in a non-blocking manner.
 */
void loop(void)
{
    /* Update LED blink state */
    led_blink_update();
    
    /* Update UART communication */
    uart_driver_update();
}