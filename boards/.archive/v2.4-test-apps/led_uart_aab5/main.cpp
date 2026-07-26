/*
 * main.c - Arduino UNO R3 (ATmega328P) firmware
 * LED blink at 200ms interval, serial "HELLO" every 2 seconds
 * F_CPU = 16MHz, 9600 baud
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
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=aab50dd2\n";
        for (const char* p = sig; *p; p++) {
            while (!(UCSR0A & (1 << UDRE0))) { }
            UDR0 = (unsigned char)(*p);
        }
    }
} _firmforge_boot;
}

/* ======================== Module: led_blink ======================== */

/**
 * @brief Initialize LED pin as output
 */
void led_blink_init(void)
{
    pinMode(LED_BUILTIN, OUTPUT);
    digitalWrite(LED_BUILTIN, LOW);
}

/**
 * @brief Toggle LED state (non-blocking, called periodically)
 */
void led_blink_toggle(void)
{
    static uint8_t led_state = LOW;
    led_state = (led_state == HIGH) ? LOW : HIGH;
    digitalWrite(LED_BUILTIN, led_state);
}

/* ======================== Module: uart_driver ======================== */

/**
 * @brief Initialize UART at 9600 baud
 */
void uart_driver_init(void)
{
    Serial.begin(9600);
}

/**
 * @brief Send "HELLO" string over UART
 */
void uart_driver_send_hello(void)
{
    Serial.println("HELLO");
}

/* ======================== Main Application ======================== */

/* Timing constants (in milliseconds) */
#define LED_BLINK_INTERVAL_MS   200UL
#define UART_HELLO_INTERVAL_MS  2000UL

/* Timing variables for non-blocking scheduling */
static unsigned long last_led_toggle_ms = 0;
static unsigned long last_uart_hello_ms = 0;

void setup(void)
{
    /* Initialize modules */
    led_blink_init();
    uart_driver_init();
}

void loop(void)
{
    unsigned long current_ms = millis();

    /* Task 1: LED blink every 200ms */
    if (current_ms - last_led_toggle_ms >= LED_BLINK_INTERVAL_MS)
    {
        last_led_toggle_ms = current_ms;
        led_blink_toggle();
    }

    /* Task 2: Send "HELLO" every 2 seconds */
    if (current_ms - last_uart_hello_ms >= UART_HELLO_INTERVAL_MS)
    {
        last_uart_hello_ms = current_ms;
        uart_driver_send_hello();
    }
}