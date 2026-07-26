#include <Arduino.h>
/* FirmForge Boot Signature — AVR UART0 (TX=pin1, 9600) */
namespace {
struct _FirmForgeBoot {
    _FirmForgeBoot() {
        UBRR0H = (unsigned char)(103 >> 8);
        UBRR0L = (unsigned char)(103);
        UCSR0B = (1 << TXEN0);
        UCSR0C = (3 << UCSZ00);
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=8bf6bc65\n";
        for (const char* p = sig; *p; p++) {
            while (!(UCSR0A & (1 << UDRE0))) { }
            UDR0 = (unsigned char)(*p);
        }
    }
} _firmforge_boot;
}

/*
 * main.c - LED blink and UART communication for Arduino UNO R3 (ATmega328P)
 * 
 * Features:
 * 1. LED_BUILTIN (pin 13) blinks with 500ms period
 * 2. Serial communication at 9600 baud, prints status message
 */

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** LED blink interval in milliseconds */
#define LED_BLINK_INTERVAL_MS  500U

/** Serial communication baud rate */
#define SERIAL_BAUD_RATE       9600UL

/** Delay between serial status messages in milliseconds */
#define SERIAL_STATUS_INTERVAL_MS  1000U

// ---------------------------------------------------------------------------
// Function prototypes
// ---------------------------------------------------------------------------

/**
 * @brief Initialize the built-in LED pin as output.
 */
static void led_blink_init(void);

/**
 * @brief Toggle the built-in LED state.
 */
static void led_blink_toggle(void);

/**
 * @brief Initialize UART (Serial) at the configured baud rate.
 */
static void uart_driver_init(void);

/**
 * @brief Send a status message over UART.
 */
static void uart_driver_send_status(void);

// ---------------------------------------------------------------------------
// Module: led_blink
// ---------------------------------------------------------------------------

/**
 * @brief Initialize the built-in LED pin as output.
 */
static void led_blink_init(void)
{
    pinMode(LED_BUILTIN, OUTPUT);
    digitalWrite(LED_BUILTIN, LOW);  // start with LED off
}

/**
 * @brief Toggle the built-in LED state.
 */
static void led_blink_toggle(void)
{
    static uint8_t led_state = LOW;
    led_state = (led_state == LOW) ? HIGH : LOW;
    digitalWrite(LED_BUILTIN, led_state);
}

// ---------------------------------------------------------------------------
// Module: uart_driver
// ---------------------------------------------------------------------------

/**
 * @brief Initialize UART (Serial) at the configured baud rate.
 */
static void uart_driver_init(void)
{
    Serial.begin(SERIAL_BAUD_RATE);
}

/**
 * @brief Send a status message over UART.
 */
static void uart_driver_send_status(void)
{
    Serial.println("System OK - LED blinking at 500ms");
}

// ---------------------------------------------------------------------------
// Arduino entry points: setup() and loop()
// ---------------------------------------------------------------------------

/**
 * @brief Arduino setup function.
 * 
 * Initializes the LED pin and UART communication.
 */
void setup(void)
{
    led_blink_init();
    uart_driver_init();
}

/**
 * @brief Arduino main loop.
 * 
 * Blinks the built-in LED at 500ms intervals and prints a status message
 * every second over UART.
 */
void loop(void)
{
    static unsigned long last_blink_ms = 0UL;
    static unsigned long last_status_ms = 0UL;
    unsigned long current_ms = millis();

    // Non-blocking LED blink every LED_BLINK_INTERVAL_MS
    if (current_ms - last_blink_ms >= LED_BLINK_INTERVAL_MS)
    {
        last_blink_ms = current_ms;
        led_blink_toggle();
    }

    // Non-blocking serial status message every SERIAL_STATUS_INTERVAL_MS
    if (current_ms - last_status_ms >= SERIAL_STATUS_INTERVAL_MS)
    {
        last_status_ms = current_ms;
        uart_driver_send_status();
    }
}