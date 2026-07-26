/*
 * main.c - LED blink and UART communication for Arduino UNO R3 (ATmega328P)
 * 
 * Features:
 * 1. LED (pin 13) blinks with 200ms period
 * 2. Serial prints "HELLO" at 9600 baud every 2 seconds
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
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=1655c80f\n";
        for (const char* p = sig; *p; p++) {
            while (!(UCSR0A & (1 << UDRE0))) { }
            UDR0 = (unsigned char)(*p);
        }
    }
} _firmforge_boot;
}

/* ======================== Constants ======================== */

/* LED blink timing */
#define LED_BLINK_INTERVAL_MS      200u   /* LED on/off period in milliseconds */

/* Serial communication */
#define SERIAL_BAUD_RATE           9600ul /* UART baud rate */
#define SERIAL_PRINT_INTERVAL_MS   2000u  /* Interval between "HELLO" prints in ms */
#define SERIAL_MESSAGE             "HELLO"

/* ======================== Module: led_blink ======================== */

/**
 * @brief Initialize the LED pin as output.
 * 
 * Sets the built-in LED pin (Arduino pin 13) to OUTPUT mode.
 */
static void led_blink_init(void)
{
    pinMode(LED_BUILTIN, OUTPUT);
    digitalWrite(LED_BUILTIN, LOW);  /* Start with LED off */
}

/**
 * @brief Toggle the LED state.
 * 
 * Reads the current state of the LED pin and toggles it.
 * This function is called periodically to achieve blinking.
 */
static void led_blink_toggle(void)
{
    static uint8_t led_state = LOW;
    
    led_state = (led_state == HIGH) ? LOW : HIGH;
    digitalWrite(LED_BUILTIN, led_state);
}

/* ======================== Module: uart_driver ======================== */

/**
 * @brief Initialize UART communication.
 * 
 * Configures the serial port with the specified baud rate.
 * Must be called once in setup().
 */
static void uart_driver_init(void)
{
    Serial.begin(SERIAL_BAUD_RATE);
}

/**
 * @brief Print "HELLO" message over serial.
 * 
 * Sends the predefined message string followed by a newline.
 */
static void uart_driver_print_hello(void)
{
    Serial.println(SERIAL_MESSAGE);
}

/* ======================== Main Application ======================== */

/**
 * @brief Arduino setup function.
 * 
 * Initializes all modules:
 * - LED blink module (pin mode)
 * - UART driver (serial communication)
 * 
 * Called once at startup.
 */
void setup(void)
{
    /* Initialize modules */
    led_blink_init();
    uart_driver_init();
}

/**
 * @brief Arduino main loop.
 * 
 * Runs continuously after setup():
 * - Toggles LED every 200ms using non-blocking delay
 * - Prints "HELLO" every 2 seconds using non-blocking timing
 * 
 * Uses millis() for non-blocking timing to allow concurrent operations.
 */
void loop(void)
{
    static unsigned long last_led_toggle_ms = 0u;
    static unsigned long last_serial_print_ms = 0u;
    unsigned long current_ms = millis();
    
    /* --- LED Blink Task --- */
    if ((current_ms - last_led_toggle_ms) >= LED_BLINK_INTERVAL_MS)
    {
        last_led_toggle_ms = current_ms;
        led_blink_toggle();
    }
    
    /* --- Serial Print Task --- */
    if ((current_ms - last_serial_print_ms) >= SERIAL_PRINT_INTERVAL_MS)
    {
        last_serial_print_ms = current_ms;
        uart_driver_print_hello();
    }
}