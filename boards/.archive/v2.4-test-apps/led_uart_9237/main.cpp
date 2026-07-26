#include <Arduino.h>
/* FirmForge Boot Signature — AVR UART0 (TX=pin1, 9600) */
namespace {
struct _FirmForgeBoot {
    _FirmForgeBoot() {
        UBRR0H = (unsigned char)(103 >> 8);
        UBRR0L = (unsigned char)(103);
        UCSR0B = (1 << TXEN0);
        UCSR0C = (3 << UCSZ00);
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=923777d4\n";
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
 * 1. LED blink every 500ms
 * 2. Serial print "HELLO" every 1 second at 9600 baud
 */

// ============================================================================
// Module: led_blink
// Description: Controls the built-in LED with a 500ms toggle period
// ============================================================================

/**
 * @brief Initialize the LED pin as output
 */
void led_blink_init(void)
{
    pinMode(LED_BUILTIN, OUTPUT);
    digitalWrite(LED_BUILTIN, LOW);
}

/**
 * @brief Toggle the LED state
 * 
 * Called every 500ms to create a blinking effect.
 */
void led_blink_toggle(void)
{
    static uint8_t led_state = LOW;
    
    led_state = (led_state == LOW) ? HIGH : LOW;
    digitalWrite(LED_BUILTIN, led_state);
}

// ============================================================================
// Module: uart_driver
// Description: UART communication at 9600 baud
// ============================================================================

/**
 * @brief Initialize UART at 9600 baud
 */
void uart_driver_init(void)
{
    Serial.begin(9600);
}

/**
 * @brief Print "HELLO" message over UART
 * 
 * Called every 1 second.
 */
void uart_driver_print_hello(void)
{
    Serial.println("HELLO");
}

// ============================================================================
// Main application
// ============================================================================

// Timing constants (in milliseconds)
#define LED_BLINK_INTERVAL_MS  500
#define UART_PRINT_INTERVAL_MS 1000

void setup(void)
{
    // Initialize all modules
    led_blink_init();
    uart_driver_init();
}

void loop(void)
{
    static unsigned long last_led_toggle_ms = 0;
    static unsigned long last_uart_print_ms = 0;
    unsigned long current_ms = millis();

    // Task 1: LED blink every 500ms (non-blocking)
    if (current_ms - last_led_toggle_ms >= LED_BLINK_INTERVAL_MS)
    {
        last_led_toggle_ms = current_ms;
        led_blink_toggle();
    }

    // Task 2: Print "HELLO" every 1 second (non-blocking)
    if (current_ms - last_uart_print_ms >= UART_PRINT_INTERVAL_MS)
    {
        last_uart_print_ms = current_ms;
        uart_driver_print_hello();
    }
}