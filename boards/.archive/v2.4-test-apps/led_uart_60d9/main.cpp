/*
 * main.c - Arduino UNO R3 (ATmega328P) firmware
 * 
 * Features:
 * 1. LED blinking at 200ms interval
 * 2. UART communication at 9600 baud
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
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=60d9f0b1\n";
        for (const char* p = sig; *p; p++) {
            while (!(UCSR0A & (1 << UDRE0))) { }
            UDR0 = (unsigned char)(*p);
        }
    }
} _firmforge_boot;
}

/* ========================================================================== */
/* Module: led_blink                                                          */
/* Description: Controls the built-in LED with a 200ms toggle interval        */
/* ========================================================================== */

/**
 * @brief Initialize the LED pin as output
 */
static void led_blink_init(void)
{
    pinMode(LED_BUILTIN, OUTPUT);
    digitalWrite(LED_BUILTIN, LOW);
}

/**
 * @brief Toggle the LED state
 * 
 * This function toggles the built-in LED and provides a 200ms delay
 * to create a visible blinking pattern.
 */
static void led_blink_update(void)
{
    static uint8_t led_state = LOW;
    
    led_state = (led_state == HIGH) ? LOW : HIGH;
    digitalWrite(LED_BUILTIN, led_state);
    
    delay(200);
}

/* ========================================================================== */
/* Module: uart_driver                                                        */
/* Description: UART communication at 9600 baud for sending messages          */
/* ========================================================================== */

/**
 * @brief Initialize UART at 9600 baud
 */
static void uart_driver_init(void)
{
    Serial.begin(9600);
    
    /* Wait for serial port to stabilize (optional, for USB-serial adapters) */
    delay(100);
}

/**
 * @brief Send "HELLO" message over UART
 * 
 * This function transmits the string "HELLO" followed by a newline
 * to the serial console.
 */
static void uart_driver_send_hello(void)
{
    Serial.println("HELLO");
}

/* ========================================================================== */
/* Main application                                                           */
/* ========================================================================== */

/**
 * @brief Arduino setup function
 * 
 * Initializes all modules:
 * - LED blinking module
 * - UART communication module
 */
void setup(void)
{
    led_blink_init();
    uart_driver_init();
}

/**
 * @brief Arduino main loop
 * 
 * Executes the two main tasks:
 * 1. Toggle LED with 200ms delay
 * 2. Send "HELLO" message over UART
 * 
 * Both tasks run sequentially in a synchronous manner.
 */
void loop(void)
{
    led_blink_update();
    uart_driver_send_hello();
}