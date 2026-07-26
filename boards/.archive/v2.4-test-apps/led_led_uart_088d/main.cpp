#include <Arduino.h>
/* FirmForge Boot Signature — AVR UART0 (TX=pin1, 9600) */
namespace {
struct _FirmForgeBoot {
    _FirmForgeBoot() {
        UBRR0H = (unsigned char)(103 >> 8);
        UBRR0L = (unsigned char)(103);
        UCSR0B = (1 << TXEN0);
        UCSR0C = (3 << UCSZ00);
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=088dc08e\n";
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
 *         Called once during setup.
 */
void led_blink_init(void)
{
    pinMode(LED_BUILTIN, OUTPUT);
    digitalWrite(LED_BUILTIN, LOW);
}

/**
 * @brief  Non‑blocking blink update.
 *         Toggles the LED every 500 ms using millis().
 *         Must be called repeatedly from loop().
 */
void led_blink_update(void)
{
    static unsigned long last_toggle = 0;
    const unsigned long interval = 500;

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
 * @brief  Initializes the heartbeat state.
 *         Assumes the LED pin is already set as OUTPUT by led_blink_init().
 */
void led_heartbeat_init(void)
{
    /* No additional pin setup needed – reuse LED_BUILTIN */
}

/**
 * @brief  Non‑blocking heartbeat update.
 *         Produces a 50 ms pulse every 1000 ms.
 *         Must be called repeatedly from loop().
 */
void led_heartbeat_update(void)
{
    static unsigned long last_beat = 0;
    static enum { IDLE, PULSE } state = IDLE;
    const unsigned long beat_interval = 1000;
    const unsigned long pulse_duration = 50;

    unsigned long now = millis();

    switch (state)
    {
        case IDLE:
            if (now - last_beat >= beat_interval)
            {
                last_beat = now;
                digitalWrite(LED_BUILTIN, HIGH);
                state = PULSE;
            }
            break;

        case PULSE:
            if (now - last_beat >= pulse_duration)
            {
                digitalWrite(LED_BUILTIN, LOW);
                state = IDLE;
            }
            break;
    }
}

/* ========================================================================== */
/*  Module: UART Driver                                                       */
/*  Description: Initialises serial communication and sends a heartbeat       */
/*               message every second.                                        */
/*  File: apps/task/uart_driver.c                                             */
/* ========================================================================== */

/**
 * @brief  Initialises the UART at 9600 baud.
 *         Called once during setup.
 */
void uart_driver_init(void)
{
    Serial.begin(9600);
}

/**
 * @brief  Non‑blocking UART heartbeat.
 *         Prints "HEARTBEAT" every 1000 ms.
 *         Must be called repeatedly from loop().
 */
void uart_driver_update(void)
{
    static unsigned long last_print = 0;
    const unsigned long print_interval = 1000;

    unsigned long now = millis();
    if (now - last_print >= print_interval)
    {
        last_print = now;
        Serial.println("HEARTBEAT");
    }
}

/* ========================================================================== */
/*  Main Application                                                          */
/*  Description: Arduino setup() and loop() that orchestrate all modules.     */
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
 *         Calls each module's update function repeatedly.
 */
void loop(void)
{
    led_blink_update();
    led_heartbeat_update();
    uart_driver_update();
}