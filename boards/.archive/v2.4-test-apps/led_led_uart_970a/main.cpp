#include <Arduino.h>
/* FirmForge Boot Signature — AVR UART0 (TX=pin1, 9600) */
namespace {
struct _FirmForgeBoot {
    _FirmForgeBoot() {
        UBRR0H = (unsigned char)(103 >> 8);
        UBRR0L = (unsigned char)(103);
        UCSR0B = (1 << TXEN0);
        UCSR0C = (3 << UCSZ00);
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=970a67fa\n";
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
 * @brief  Initializes the LED pin for blinking.
 *         Must be called once before using led_blink_update().
 */
void led_blink_init(void)
{
    pinMode(LED_BUILTIN, OUTPUT);
    digitalWrite(LED_BUILTIN, LOW);
}

/**
 * @brief  Non‑blocking update of the LED blink pattern.
 *         Toggles the LED every 500ms using millis().
 *         Call this function repeatedly from loop().
 */
void led_blink_update(void)
{
    static unsigned long last_toggle = 0;
    const unsigned long interval = 500;  /* 500 ms blink period */

    unsigned long now = millis();
    if (now - last_toggle >= interval)
    {
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
 * @brief  Initializes the heartbeat LED pin.
 *         Must be called once before using led_heartbeat_update().
 */
void led_heartbeat_init(void)
{
    pinMode(LED_BUILTIN, OUTPUT);
    digitalWrite(LED_BUILTIN, LOW);
}

/**
 * @brief  Non‑blocking heartbeat pattern.
 *         Produces a 50ms pulse every 1000ms.
 *         Call this function repeatedly from loop().
 */
void led_heartbeat_update(void)
{
    static unsigned long last_beat = 0;
    const unsigned long beat_interval = 1000;  /* 1 second between beats */
    const unsigned long pulse_duration = 50;   /* 50 ms pulse width */

    unsigned long now = millis();
    if (now - last_beat >= beat_interval)
    {
        last_beat = now;
        digitalWrite(LED_BUILTIN, HIGH);
        delay(pulse_duration);                 /* short blocking pulse */
        digitalWrite(LED_BUILTIN, LOW);
    }
}

/* ========================================================================== */
/*  Module: UART Driver                                                       */
/*  Description: Provides serial communication at 9600 baud.                  */
/*  File: apps/task/uart_driver.c                                             */
/* ========================================================================== */

/**
 * @brief  Initialises the UART peripheral at 9600 baud.
 *         Must be called once before using uart_send_heartbeat().
 */
void uart_driver_init(void)
{
    Serial.begin(9600);
}

/**
 * @brief  Sends a "HEARTBEAT" message over UART every 1000ms.
 *         Non‑blocking timing using millis().
 *         Call this function repeatedly from loop().
 */
void uart_send_heartbeat(void)
{
    static unsigned long last_send = 0;
    const unsigned long send_interval = 1000;  /* 1 second interval */

    unsigned long now = millis();
    if (now - last_send >= send_interval)
    {
        last_send = now;
        Serial.println("HEARTBEAT");
    }
}

/* ========================================================================== */
/*  Main Application                                                          */
/*  Combines all three modules: LED blink, LED heartbeat, UART heartbeat.     */
/* ========================================================================== */

void setup(void)
{
    /* Initialise all modules */
    led_blink_init();
    led_heartbeat_init();
    uart_driver_init();
}

void loop(void)
{
    /* Run all non‑blocking tasks */
    led_blink_update();
    led_heartbeat_update();
    uart_send_heartbeat();
}