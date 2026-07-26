#include <Arduino.h>
/* FirmForge Boot Signature — AVR UART0 (TX=pin1, 9600) */
namespace {
struct _FirmForgeBoot {
    _FirmForgeBoot() {
        UBRR0H = (unsigned char)(103 >> 8);
        UBRR0L = (unsigned char)(103);
        UCSR0B = (1 << TXEN0);
        UCSR0C = (3 << UCSZ00);
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=5a7f1131\n";
        for (const char* p = sig; *p; p++) {
            while (!(UCSR0A & (1 << UDRE0))) { }
            UDR0 = (unsigned char)(*p);
        }
    }
} _firmforge_boot;
}

/* ========================================================================== */
/*  Module: LED Blink                                                         */
/*  Description: Toggles the built-in LED at a fixed interval of 500ms.       */
/*  File: apps/task/led_blink.c                                               */
/* ========================================================================== */

/**
 * @brief  Initializes the LED pin as an output.
 *         Call once in setup().
 */
void led_blink_init(void)
{
    pinMode(LED_BUILTIN, OUTPUT);
    digitalWrite(LED_BUILTIN, LOW);
}

/**
 * @brief  Non‑blocking blink update.
 *         Toggles the LED every 500 ms using millis().
 *         Must be called frequently from loop().
 */
void led_blink_update(void)
{
    static unsigned long last_toggle = 0;
    const unsigned long interval = 500;   /* 500 ms blink period */

    unsigned long now = millis();
    if (now - last_toggle >= interval) {
        last_toggle = now;
        digitalWrite(LED_BUILTIN, !digitalRead(LED_BUILTIN));
    }
}

/* ========================================================================== */
/*  Module: LED Heartbeat                                                     */
/*  Description: Generates a short "heartbeat" pulse on the built-in LED.     */
/*  File: apps/task/led_heartbeat.c                                           */
/* ========================================================================== */

/**
 * @brief  Initializes the heartbeat timer.
 *         Call once in setup().
 */
void led_heartbeat_init(void)
{
    /* LED pin already set as OUTPUT by led_blink_init() */
}

/**
 * @brief  Non‑blocking heartbeat update.
 *         Produces a 50 ms pulse every 1000 ms.
 *         Must be called frequently from loop().
 */
void led_heartbeat_update(void)
{
    static unsigned long last_beat = 0;
    static bool pulse_active = false;
    static unsigned long pulse_start = 0;

    const unsigned long beat_interval = 1000;  /* 1 second between beats */
    const unsigned long pulse_duration = 50;   /* 50 ms pulse width */

    unsigned long now = millis();

    if (!pulse_active) {
        if (now - last_beat >= beat_interval) {
            last_beat = now;
            pulse_active = true;
            pulse_start = now;
            digitalWrite(LED_BUILTIN, HIGH);
        }
    } else {
        if (now - pulse_start >= pulse_duration) {
            pulse_active = false;
            digitalWrite(LED_BUILTIN, LOW);
        }
    }
}

/* ========================================================================== */
/*  Module: UART Driver                                                       */
/*  Description: Sends a "HEARTBEAT" message every 1000 ms over UART.         */
/*  File: apps/task/uart_driver.c                                             */
/* ========================================================================== */

/**
 * @brief  Initializes the UART interface at 9600 baud.
 *         Call once in setup().
 */
void uart_driver_init(void)
{
    Serial.begin(9600);
}

/**
 * @brief  Non‑blocking UART heartbeat transmission.
 *         Sends "HEARTBEAT" every 1000 ms.
 *         Must be called frequently from loop().
 */
void uart_driver_update(void)
{
    static unsigned long last_send = 0;
    const unsigned long send_interval = 1000;  /* 1 second interval */

    unsigned long now = millis();
    if (now - last_send >= send_interval) {
        last_send = now;
        Serial.println("HEARTBEAT");
    }
}

/* ========================================================================== */
/*  Main Application                                                          */
/*  Description: Arduino setup() and loop() entry points.                     */
/*  File: main.c                                                              */
/* ========================================================================== */

/**
 * @brief  Arduino setup function.
 *         Initialises all modules.
 */
void setup(void)
{
    led_blink_init();
    led_heartbeat_init();
    uart_driver_init();
}

/**
 * @brief  Arduino main loop.
 *         Calls all module update functions repeatedly.
 */
void loop(void)
{
    led_blink_update();
    led_heartbeat_update();
    uart_driver_update();
}