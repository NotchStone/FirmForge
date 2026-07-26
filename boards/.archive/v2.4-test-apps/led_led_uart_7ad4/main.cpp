#include <Arduino.h>
/* FirmForge Boot Signature — AVR UART0 (TX=pin1, 9600) */
namespace {
struct _FirmForgeBoot {
    _FirmForgeBoot() {
        UBRR0H = (unsigned char)(103 >> 8);
        UBRR0L = (unsigned char)(103);
        UCSR0B = (1 << TXEN0);
        UCSR0C = (3 << UCSZ00);
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=7ad460f6\n";
        for (const char* p = sig; *p; p++) {
            while (!(UCSR0A & (1 << UDRE0))) { }
            UDR0 = (unsigned char)(*p);
        }
    }
} _firmforge_boot;
}

/* ============================================================
 *  Constants and Definitions
 * ============================================================ */

/* LED blink timing (milliseconds) */
#define BLINK_INTERVAL_MS  1000UL

/* Serial communication baud rate */
#define SERIAL_BAUD_RATE   9600UL

/* Heartbeat counter initial value */
#define HEARTBEAT_COUNT_INIT  0

/* ============================================================
 *  Module: led_blink
 *  Description: Controls the built-in LED on/off state.
 *  Dependencies: None
 * ============================================================ */

/**
 * @brief  Initialize the LED pin as an output.
 *         Must be called once before using led_blink_set().
 */
void led_blink_init(void)
{
    pinMode(LED_BUILTIN, OUTPUT);
    digitalWrite(LED_BUILTIN, LOW);
}

/**
 * @brief  Set the LED state (HIGH = on, LOW = off).
 * @param  state  HIGH or LOW
 */
void led_blink_set(uint8_t state)
{
    digitalWrite(LED_BUILTIN, state);
}

/* ============================================================
 *  Module: led_heartbeat
 *  Description: Provides a heartbeat counter that increments
 *               each time the LED toggles.
 *  Dependencies: None
 * ============================================================ */

/* Heartbeat counter, incremented on each blink cycle */
static uint32_t heartbeat_count = HEARTBEAT_COUNT_INIT;

/**
 * @brief  Initialize the heartbeat counter to zero.
 */
void led_heartbeat_init(void)
{
    heartbeat_count = HEARTBEAT_COUNT_INIT;
}

/**
 * @brief  Increment the heartbeat counter by one.
 */
void led_heartbeat_tick(void)
{
    heartbeat_count++;
}

/**
 * @brief  Get the current heartbeat count.
 * @return Current heartbeat count value.
 */
uint32_t led_heartbeat_get_count(void)
{
    return heartbeat_count;
}

/* ============================================================
 *  Module: uart_driver
 *  Description: Handles UART serial communication.
 *  Dependencies: None
 * ============================================================ */

/**
 * @brief  Initialize UART serial communication at the given baud rate.
 * @param  baud  Baud rate (e.g., 9600, 115200)
 */
void uart_driver_init(unsigned long baud)
{
    Serial.begin(baud);
}

/**
 * @brief  Send a heartbeat message over UART with the current count.
 * @param  count  Heartbeat counter value to include in the message.
 */
void uart_driver_send_heartbeat(uint32_t count)
{
    Serial.print("HEARTBEAT ");
    Serial.println(count);
}

/* ============================================================
 *  Arduino Setup and Loop
 * ============================================================ */

/**
 * @brief  Arduino setup function.
 *         Initializes all modules once at startup.
 */
void setup(void)
{
    /* Initialize LED blink module */
    led_blink_init();

    /* Initialize heartbeat counter */
    led_heartbeat_init();

    /* Initialize UART serial communication */
    uart_driver_init(SERIAL_BAUD_RATE);
}

/**
 * @brief  Arduino loop function.
 *         Runs repeatedly: toggles LED, increments heartbeat,
 *         and prints the heartbeat count over UART.
 */
void loop(void)
{
    /* Turn LED on */
    led_blink_set(HIGH);

    /* Wait for the on interval */
    delay(BLINK_INTERVAL_MS);

    /* Turn LED off */
    led_blink_set(LOW);

    /* Increment heartbeat counter */
    led_heartbeat_tick();

    /* Send heartbeat message over UART */
    uart_driver_send_heartbeat(led_heartbeat_get_count());

    /* Wait for the off interval */
    delay(BLINK_INTERVAL_MS);
}