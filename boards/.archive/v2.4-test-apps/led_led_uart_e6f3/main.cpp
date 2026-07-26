#include <Arduino.h>
/* FirmForge Boot Signature — AVR UART0 (TX=pin1, 9600) */
namespace {
struct _FirmForgeBoot {
    _FirmForgeBoot() {
        UBRR0H = (unsigned char)(103 >> 8);
        UBRR0L = (unsigned char)(103);
        UCSR0B = (1 << TXEN0);
        UCSR0C = (3 << UCSZ00);
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=e6f3fb59\n";
        for (const char* p = sig; *p; p++) {
            while (!(UCSR0A & (1 << UDRE0))) { }
            UDR0 = (unsigned char)(*p);
        }
    }
} _firmforge_boot;
}

/* ============================================================
 *  Constants and Pin Definitions
 * ============================================================ */
#define LED_PIN             13      /* Built-in LED on Arduino UNO R3 */
#define SERIAL_BAUD         9600    /* UART baud rate */

/* ============================================================
 *  Module: led_blink
 *  Description: Toggles the built-in LED at 500ms interval.
 *  File: apps/task/led_blink.c
 * ============================================================ */
static void led_blink_init(void)
{
    pinMode(LED_PIN, OUTPUT);
    digitalWrite(LED_PIN, LOW);
}

static void led_blink_update(void)
{
    static unsigned long last_toggle = 0;
    unsigned long now = millis();

    if (now - last_toggle >= 500) {
        last_toggle = now;
        digitalWrite(LED_PIN, !digitalRead(LED_PIN));
    }
}

/* ============================================================
 *  Module: led_heartbeat
 *  Description: Sends a heartbeat indication via LED (short pulse).
 *  File: apps/task/led_heartbeat.c
 * ============================================================ */
static void led_heartbeat_init(void)
{
    /* LED pin already initialized in led_blink_init() */
}

static void led_heartbeat_update(void)
{
    static unsigned long last_beat = 0;
    unsigned long now = millis();

    /* Heartbeat every 1000 ms: short 50ms pulse */
    if (now - last_beat >= 1000) {
        last_beat = now;
        digitalWrite(LED_PIN, HIGH);
        delay(50);
        digitalWrite(LED_PIN, LOW);
    }
}

/* ============================================================
 *  Module: uart_driver
 *  Description: Prints a heartbeat counter over UART at 9600 baud.
 *  File: apps/task/uart_driver.c
 * ============================================================ */
static void uart_driver_init(void)
{
    Serial.begin(SERIAL_BAUD);
}

static void uart_driver_update(void)
{
    static unsigned long last_print = 0;
    static unsigned long count = 0;
    unsigned long now = millis();

    if (now - last_print >= 1000) {
        last_print = now;
        count++;
        Serial.print("HEARTBEAT count# ");
        Serial.println(count);
    }
}

/* ============================================================
 *  Arduino setup() and loop()
 * ============================================================ */
void setup(void)
{
    led_blink_init();
    led_heartbeat_init();
    uart_driver_init();
}

void loop(void)
{
    led_blink_update();
    led_heartbeat_update();
    uart_driver_update();
}