#include <Arduino.h>
/* FirmForge Boot Signature — AVR UART0 (TX=pin1, 9600) */
namespace {
struct _FirmForgeBoot {
    _FirmForgeBoot() {
        UBRR0H = (unsigned char)(103 >> 8);
        UBRR0L = (unsigned char)(103);
        UCSR0B = (1 << TXEN0);
        UCSR0C = (3 << UCSZ00);
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=c7622659\n";
        for (const char* p = sig; *p; p++) {
            while (!(UCSR0A & (1 << UDRE0))) { }
            UDR0 = (unsigned char)(*p);
        }
    }
} _firmforge_boot;
}

/*
 * main.c - Arduino UNO R3 (ATmega328P) firmware
 * 
 * Features:
 * 1. LED blink at 500ms interval
 * 2. Serial print "OK" every 1 second at 9600 baud
 * 
 * Pin assignments:
 * - LED_BUILTIN (pin 13) - built-in LED
 * - Serial: RX=pin 0, TX=pin 1
 */

// ---------------------------------------------------------------------------
// Module: led_blink
// ---------------------------------------------------------------------------

/**
 * @brief Initialize the built-in LED pin as output.
 */
void led_blink_init(void)
{
    pinMode(LED_BUILTIN, OUTPUT);
    digitalWrite(LED_BUILTIN, LOW);  // start with LED off
}

/**
 * @brief Toggle the built-in LED state.
 */
void led_blink_toggle(void)
{
    static uint8_t led_state = LOW;
    led_state = (led_state == LOW) ? HIGH : LOW;
    digitalWrite(LED_BUILTIN, led_state);
}

// ---------------------------------------------------------------------------
// Module: uart_driver
// ---------------------------------------------------------------------------

/**
 * @brief Initialize UART at 9600 baud.
 */
void uart_driver_init(void)
{
    Serial.begin(9600);
}

/**
 * @brief Print "OK" message over UART.
 */
void uart_driver_print_ok(void)
{
    Serial.println("OK");
}

// ---------------------------------------------------------------------------
// Main application
// ---------------------------------------------------------------------------

/**
 * @brief Arduino setup function - called once at startup.
 */
void setup(void)
{
    // Initialize all modules
    led_blink_init();
    uart_driver_init();
}

/**
 * @brief Arduino main loop - runs repeatedly.
 * 
 * Scheduling:
 * - LED toggles every 500ms
 * - Serial "OK" printed every 1000ms
 * 
 * Uses non-blocking millis() timing for both tasks.
 */
void loop(void)
{
    static unsigned long last_led_toggle = 0;
    static unsigned long last_serial_print = 0;
    const unsigned long led_interval = 500;   // 500 ms
    const unsigned long serial_interval = 1000; // 1000 ms

    unsigned long now = millis();

    // Task 1: LED blink every 500ms
    if (now - last_led_toggle >= led_interval)
    {
        last_led_toggle = now;
        led_blink_toggle();
    }

    // Task 2: Serial print "OK" every 1000ms
    if (now - last_serial_print >= serial_interval)
    {
        last_serial_print = now;
        uart_driver_print_ok();
    }
}