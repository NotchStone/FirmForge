/*
 * main.c - Arduino UNO R3 (ATmega328P) firmware
 * 
 * Features:
 * 1. LED blink on built-in LED (pin 13) with 200ms period
 * 2. UART communication at 9600 baud, printing "HELLO" periodically
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
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=44b3c127\n";
        for (const char* p = sig; *p; p++) {
            while (!(UCSR0A & (1 << UDRE0))) { }
            UDR0 = (unsigned char)(*p);
        }
    }
} _firmforge_boot;
}

/* ==========================================================================
 * Module: led_blink
 * Description: Controls the built-in LED with a 200ms blink period.
 * File: apps/task/led_blink.c (functions integrated here)
 * ========================================================================== */

/**
 * @brief Initialize the LED pin as output.
 */
static void led_blink_init(void)
{
    pinMode(LED_BUILTIN, OUTPUT);
    digitalWrite(LED_BUILTIN, LOW);  /* Start with LED off */
}

/**
 * @brief Toggle the LED state with a 200ms delay.
 *        This function blocks for 200ms.
 */
static void led_blink_update(void)
{
    digitalWrite(LED_BUILTIN, HIGH);  /* Turn LED on */
    delay(100);                       /* Wait 100ms */

    digitalWrite(LED_BUILTIN, LOW);   /* Turn LED off */
    delay(100);                       /* Wait 100ms */
}

/* ==========================================================================
 * Module: uart_driver
 * Description: Handles UART communication at 9600 baud.
 * File: apps/task/uart_driver.c (functions integrated here)
 * ========================================================================== */

/**
 * @brief Initialize UART at 9600 baud.
 */
static void uart_driver_init(void)
{
    Serial.begin(9600);
    /* Wait for serial port to stabilize (optional, for USB-serial adapters) */
    delay(100);
}

/**
 * @brief Send "HELLO" message over UART.
 *        This function blocks for the duration of the print.
 */
static void uart_driver_send_hello(void)
{
    Serial.println("HELLO");
}

/* ==========================================================================
 * Main Arduino entry points: setup() and loop()
 * ========================================================================== */

/**
 * @brief Arduino setup function.
 *        Called once at startup to initialize all modules.
 */
void setup(void)
{
    /* Initialize all functional modules */
    led_blink_init();
    uart_driver_init();
}

/**
 * @brief Arduino main loop function.
 *        Called repeatedly after setup().
 *        Implements LED blink and periodic UART message.
 */
void loop(void)
{
    /* Task 1: Blink LED with 200ms period (100ms on, 100ms off) */
    led_blink_update();

    /* Task 2: Send "HELLO" over UART at 9600 baud */
    uart_driver_send_hello();
}