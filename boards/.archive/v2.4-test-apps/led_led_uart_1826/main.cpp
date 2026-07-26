#include <Arduino.h>
/* FirmForge Boot Signature — AVR UART0 (TX=pin1, 9600) */
namespace {
struct _FirmForgeBoot {
    _FirmForgeBoot() {
        UBRR0H = (unsigned char)(103 >> 8);
        UBRR0L = (unsigned char)(103);
        UCSR0B = (1 << TXEN0);
        UCSR0C = (3 << UCSZ00);
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=1826514f\n";
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
#define LED_PIN             LED_BUILTIN   /* Arduino pin 13, PB7 */
#define SERIAL_BAUD         9600UL        /* UART baud rate */
#define BLINK_INTERVAL_MS   1000UL        /* 1 second on, 1 second off */

/* ============================================================
 *  Module: led_blink
 *  Description: Toggles the built-in LED on/off.
 *  Dependencies: None
 * ============================================================ */
static void led_blink_init(void)
{
    pinMode(LED_PIN, OUTPUT);
    digitalWrite(LED_PIN, LOW);
}

static void led_blink_toggle(void)
{
    static uint8_t led_state = LOW;
    led_state = (led_state == LOW) ? HIGH : LOW;
    digitalWrite(LED_PIN, led_state);
}

/* ============================================================
 *  Module: led_heartbeat
 *  Description: Provides a heartbeat indication via LED.
 *               Calls led_blink_toggle() each cycle.
 *  Dependencies: led_blink
 * ============================================================ */
static void led_heartbeat_init(void)
{
    /* No additional init needed; relies on led_blink_init() */
}

static void led_heartbeat_run(void)
{
    led_blink_toggle();
}

/* ============================================================
 *  Module: uart_driver
 *  Description: Initializes UART and prints heartbeat message
 *               with an incrementing counter.
 *  Dependencies: None
 * ============================================================ */
static void uart_driver_init(void)
{
    Serial.begin(SERIAL_BAUD);
    /* Wait a moment for serial to stabilize (optional) */
    delay(100);
}

static void uart_driver_send_heartbeat(void)
{
    static unsigned long count = 0;
    Serial.print("HEARTBEAT ");
    Serial.println(count);
    count++;
}

/* ============================================================
 *  Arduino Setup & Loop
 * ============================================================ */
void setup(void)
{
    /* Initialize all modules */
    led_blink_init();
    led_heartbeat_init();
    uart_driver_init();
}

void loop(void)
{
    /* Heartbeat sequence: toggle LED and send UART message */
    led_heartbeat_run();
    uart_driver_send_heartbeat();

    /* Wait for the blink interval (blocking delay for simplicity) */
    delay(BLINK_INTERVAL_MS);
}