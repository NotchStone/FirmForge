#include <Arduino.h>
/* FirmForge Boot Signature — AVR UART0 (TX=pin1, 9600) */
namespace {
struct _FirmForgeBoot {
    _FirmForgeBoot() {
        UBRR0H = (unsigned char)(103 >> 8);
        UBRR0L = (unsigned char)(103);
        UCSR0B = (1 << TXEN0);
        UCSR0C = (3 << UCSZ00);
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=33891886\n";
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
 * @brief Performs one blink cycle: toggles LED with 100ms delay.
 *        Total period = 200ms.
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
/*               Two quick pulses followed by a pause.                        */
/* ========================================================================== */

/* Heartbeat timing constants (in milliseconds) */
#define HEARTBEAT_PULSE_ON_MS   50
#define HEARTBEAT_PULSE_OFF_MS  50
#define HEARTBEAT_PAUSE_MS      500

/**
 * @brief Initializes the LED pin for heartbeat.
 */
void led_heartbeat_init(void)
{
    pinMode(LED_BUILTIN, OUTPUT);
    digitalWrite(LED_BUILTIN, LOW);
}

/**
 * @brief Performs one heartbeat cycle: two quick pulses then a pause.
 */
void led_heartbeat_update(void)
{
    /* First pulse */
    digitalWrite(LED_BUILTIN, HIGH);
    delay(HEARTBEAT_PULSE_ON_MS);
    digitalWrite(LED_BUILTIN, LOW);
    delay(HEARTBEAT_PULSE_OFF_MS);

    /* Second pulse */
    digitalWrite(LED_BUILTIN, HIGH);
    delay(HEARTBEAT_PULSE_ON_MS);
    digitalWrite(LED_BUILTIN, LOW);
    delay(HEARTBEAT_PULSE_OFF_MS);

    /* Pause between beats */
    delay(HEARTBEAT_PAUSE_MS);
}

/* ========================================================================== */
/*  Module: UART Driver                                                       */
/*  Description: Initializes and sends messages over the serial port.         */
/* ========================================================================== */

/* UART baud rate */
#define UART_BAUD_RATE  9600

/**
 * @brief Initializes the UART (Serial) interface.
 */
void uart_driver_init(void)
{
    Serial.begin(UART_BAUD_RATE);
}

/**
 * @brief Sends a heartbeat message over UART.
 */
void uart_driver_send_heartbeat(void)
{
    Serial.println("UNO Heartbeat");
}

/* ========================================================================== */
/*  Main Application                                                          */
/* ========================================================================== */

/**
 * @brief Arduino setup function. Called once at startup.
 *        Initializes all modules.
 */
void setup(void)
{
    /* Initialize all functional modules */
    led_blink_init();
    led_heartbeat_init();
    uart_driver_init();
}

/**
 * @brief Arduino loop function. Called repeatedly.
 *        Runs the LED blink and heartbeat patterns, and sends UART message.
 */
void loop(void)
{
    /* Run LED blink (200ms period) */
    led_blink_update();

    /* Run LED heartbeat (one cycle) */
    led_heartbeat_update();

    /* Send heartbeat message over UART */
    uart_driver_send_heartbeat();
}