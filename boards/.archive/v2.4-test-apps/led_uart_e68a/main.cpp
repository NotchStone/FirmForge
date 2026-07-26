/*
 * main.c - Arduino UNO R3 (ATmega328P) firmware
 * 
 * Features:
 * 1. LED blink at 200ms interval
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
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=e68a438e\n";
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
/* ========================================================================== */

/**
 * @brief Blink the built-in LED with 200ms period.
 * 
 * Toggles LED_BUILTIN (pin 13) every 200ms.
 * Must be called repeatedly from loop().
 */
void led_blink_update(void)
{
    static unsigned long last_toggle = 0;
    const unsigned long interval = 200;  /* 200ms blink interval */
    unsigned long now = millis();

    if (now - last_toggle >= interval) {
        last_toggle = now;
        digitalWrite(LED_BUILTIN, !digitalRead(LED_BUILTIN));
    }
}

/**
 * @brief Initialize LED pin as output.
 */
void led_blink_init(void)
{
    pinMode(LED_BUILTIN, OUTPUT);
    digitalWrite(LED_BUILTIN, LOW);  /* start with LED off */
}

/* ========================================================================== */
/* Module: uart_driver                                                        */
/* File: apps/task/uart_driver.c                                              */
/* ========================================================================== */

/**
 * @brief Send "HELLO" message over serial every 2 seconds.
 * 
 * Non-blocking implementation using millis().
 * Must be called repeatedly from loop().
 */
void uart_driver_update(void)
{
    static unsigned long last_send = 0;
    const unsigned long interval = 2000;  /* 2 seconds interval */
    unsigned long now = millis();

    if (now - last_send >= interval) {
        last_send = now;
        Serial.println("HELLO");
    }
}

/**
 * @brief Initialize UART at 9600 baud.
 */
void uart_driver_init(void)
{
    Serial.begin(9600);
    /* Wait for serial port to stabilize (optional, for USB-serial adapters) */
    delay(100);
}

/* ========================================================================== */
/* Main application                                                           */
/* ========================================================================== */

/**
 * @brief Arduino setup function.
 * 
 * Initializes all modules once at startup.
 */
void setup(void)
{
    led_blink_init();
    uart_driver_init();
}

/**
 * @brief Arduino main loop.
 * 
 * Runs continuously after setup().
 * Calls all module update functions.
 */
void loop(void)
{
    led_blink_update();
    uart_driver_update();
    /* No delay() here - all timing is handled by millis() in each module */
}