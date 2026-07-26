/*
 * main.c - Arduino UNO R3 (ATmega328P) firmware
 * 
 * Features:
 * 1. LED blink at 200ms interval
 * 2. Serial output "HELLO" at 9600 baud every 2 seconds
 *
 * F_CPU: 16MHz
 * Flash: 256KB, SRAM: 8KB
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
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=c1bb852b\n";
        for (const char* p = sig; *p; p++) {
            while (!(UCSR0A & (1 << UDRE0))) { }
            UDR0 = (unsigned char)(*p);
        }
    }
} _firmforge_boot;
}

/* ========================================================================== */
/* Module: led_blink                                                          */
/* Description: Controls the built-in LED with a 200ms blink interval         */
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
    delay(200);
    digitalWrite(LED_BUILTIN, LOW);
    delay(200);
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
 * This function blocks for 2 seconds after sending the message.
 * For non-blocking operation, consider using millis() based timing.
 */
void uart_driver_send_hello(void)
{
    Serial.println("HELLO");
    delay(2000);
}

/* ========================================================================== */
/* Arduino entry points: setup() and loop()                                   */
/* ========================================================================== */

/**
 * @brief Arduino setup function - runs once at startup
 * 
 * Initializes all modules and configures hardware.
 */
void setup(void)
{
    /* Initialize LED blink module */
    led_blink_init();
    
    /* Initialize UART communication */
    uart_driver_init();
}

/**
 * @brief Arduino loop function - runs repeatedly
 * 
 * Executes the main application tasks:
 * 1. Blink LED at 200ms interval
 * 2. Send "HELLO" over serial every 2 seconds
 */
void loop(void)
{
    /* Task 1: LED blink - toggles LED with 200ms delay */
    led_blink_update();
    
    /* Task 2: UART communication - sends "HELLO" with 2s delay */
    uart_driver_send_hello();
}