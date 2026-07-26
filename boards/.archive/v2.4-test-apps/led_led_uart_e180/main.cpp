#include <Arduino.h>
/* FirmForge Boot Signature — AVR UART0 (TX=pin1, 9600) */
namespace {
struct _FirmForgeBoot {
    _FirmForgeBoot() {
        UBRR0H = (unsigned char)(103 >> 8);
        UBRR0L = (unsigned char)(103);
        UCSR0B = (1 << TXEN0);
        UCSR0C = (3 << UCSZ00);
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=e1803a72\n";
        for (const char* p = sig; *p; p++) {
            while (!(UCSR0A & (1 << UDRE0))) { }
            UDR0 = (unsigned char)(*p);
        }
    }
} _firmforge_boot;
}

/* ========================================================================== */
/*  Module: LED Blink                                                         */
/*  Description: Blinks the built-in LED with a 200ms period (100ms on/off)   */
/* ========================================================================== */

/**
 * @brief Initializes the LED pin for blinking.
 */
void led_blink_init(void)
{
    pinMode(LED_BUILTIN, OUTPUT);
    digitalWrite(LED_BUILTIN, LOW);
}

/**
 * @brief Performs one blink cycle: toggles the LED and waits 100ms.
 *        Called repeatedly to achieve a 200ms period (100ms on, 100ms off).
 */
void led_blink_update(void)
{
    digitalWrite(LED_BUILTIN, HIGH);
    delay(100);
    digitalWrite(LED_BUILTIN, LOW);
    delay(100);
}

/* ========================================================================== */
/*  Module: LED Heartbeat                                                     */
/*  Description: Simulates a heartbeat pattern on the built-in LED.           */
/*               Two quick flashes followed by a pause.                       */
/* ========================================================================== */

/**
 * @brief Initializes the LED pin for heartbeat pattern.
 */
void led_heartbeat_init(void)
{
    pinMode(LED_BUILTIN, OUTPUT);
    digitalWrite(LED_BUILTIN, LOW);
}

/**
 * @brief Performs one heartbeat cycle: two short pulses then a longer pause.
 *        Pulse: 100ms on, 100ms off; pause: 600ms.
 */
void led_heartbeat_update(void)
{
    /* First pulse */
    digitalWrite(LED_BUILTIN, HIGH);
    delay(100);
    digitalWrite(LED_BUILTIN, LOW);
    delay(100);

    /* Second pulse */
    digitalWrite(LED_BUILTIN, HIGH);
    delay(100);
    digitalWrite(LED_BUILTIN, LOW);
    delay(100);

    /* Pause between heartbeats */
    delay(600);
}

/* ========================================================================== */
/*  Module: UART Driver                                                       */
/*  Description: Handles serial communication at 9600 baud.                   */
/* ========================================================================== */

/**
 * @brief Initializes UART (Serial) communication at 9600 baud.
 */
void uart_driver_init(void)
{
    Serial.begin(9600);
}

/**
 * @brief Sends the heartbeat message over UART.
 */
void uart_driver_send_heartbeat(void)
{
    Serial.println("UNO Heartbeat");
}

/* ========================================================================== */
/*  Main Application                                                          */
/*  Description: Combines LED blink, LED heartbeat, and UART output.          */
/* ========================================================================== */

/**
 * @brief Arduino setup function. Runs once at startup.
 *        Initializes all modules.
 */
void setup(void)
{
    /* Initialize UART first for debugging */
    uart_driver_init();

    /* Initialize LED modules */
    led_blink_init();
    led_heartbeat_init();

    /* Send initial message */
    uart_driver_send_heartbeat();
}

/**
 * @brief Arduino loop function. Runs repeatedly.
 *        Executes LED blink and heartbeat patterns.
 */
void loop(void)
{
    /* Perform LED blink cycle (200ms period) */
    led_blink_update();

    /* Perform LED heartbeat cycle (1000ms total) */
    led_heartbeat_update();

    /* Send heartbeat message over UART */
    uart_driver_send_heartbeat();
}