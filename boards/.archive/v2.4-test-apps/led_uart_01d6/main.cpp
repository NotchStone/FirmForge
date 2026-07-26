/*
 * main.c - LED blink and UART communication for Arduino UNO R3 (ATmega328P)
 * 
 * Features:
 * 1. LED_BUILTIN (pin 13) blinks with 200ms period
 * 2. Serial prints "HELLO" at 9600 baud every 2 seconds
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
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=01d601fd\n";
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
/* ========================================================================== */

/**
 * @brief Initialize the LED pin as output
 */
void led_blink_init(void)
{
    pinMode(LED_BUILTIN, OUTPUT);
}

/**
 * @brief Toggle the LED state
 * 
 * This function toggles the built-in LED. Call it at 200ms intervals
 * to achieve a 200ms blink period (100ms on, 100ms off).
 */
void led_blink_toggle(void)
{
    static uint8_t led_state = LOW;
    
    led_state = (led_state == LOW) ? HIGH : LOW;
    digitalWrite(LED_BUILTIN, led_state);
}

/* ========================================================================== */
/* Module: uart_driver                                                        */
/* Description: Handles UART communication at 9600 baud                       */
/* ========================================================================== */

/**
 * @brief Initialize UART at 9600 baud
 */
void uart_driver_init(void)
{
    Serial.begin(9600);
}

/**
 * @brief Send "HELLO" message over UART
 * 
 * This function prints the string "HELLO" followed by a newline.
 */
void uart_driver_send_hello(void)
{
    Serial.println("HELLO");
}

/* ========================================================================== */
/* Main application                                                           */
/* ========================================================================== */

/**
 * @brief Arduino setup function
 * 
 * Initializes all modules and runs once at startup.
 */
void setup(void)
{
    /* Initialize LED blink module */
    led_blink_init();
    
    /* Initialize UART communication at 9600 baud */
    uart_driver_init();
}

/**
 * @brief Arduino main loop
 * 
 * Runs continuously after setup(). Implements:
 * - LED toggle every 200ms
 * - Serial "HELLO" message every 2 seconds
 * 
 * Uses non-blocking timing with millis() for both tasks.
 */
void loop(void)
{
    /* Timing variables for non-block operation */
    static unsigned long last_led_toggle = 0;
    static unsigned long last_serial_msg = 0;
    
    const unsigned long led_interval = 200;   /* 200ms blink period */
    const unsigned long serial_interval = 2000; /* 2 seconds between messages */
    
    unsigned long current_time = millis();
    
    /* Task 1: Toggle LED every 200ms */
    if (current_time - last_led_toggle >= led_interval)
    {
        last_led_toggle = current_time;
        led_blink_toggle();
    }
    
    /* Task 2: Send "HELLO" over serial every 2 seconds */
    if (current_time - last_serial_msg >= serial_interval)
    {
        last_serial_msg = current_time;
        uart_driver_send_hello();
    }
}