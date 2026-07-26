#include <Arduino.h>
/* FirmForge Boot Signature — AVR UART0 (TX=pin1, 9600) */
namespace {
struct _FirmForgeBoot {
    _FirmForgeBoot() {
        UBRR0H = (unsigned char)(103 >> 8);
        UBRR0L = (unsigned char)(103);
        UCSR0B = (1 << TXEN0);
        UCSR0C = (3 << UCSZ00);
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=5b168600\n";
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
#define BLINK_INTERVAL_MS   500     /* LED blink interval in ms */
#define HEARTBEAT_INTERVAL_MS 1000  /* Heartbeat count interval in ms */

/* ============================================================
 *  Module: led_blink
 *  Description: Toggles the built-in LED at a fixed interval.
 *  Dependencies: None
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

    if (now - last_toggle >= BLINK_INTERVAL_MS) {
        last_toggle = now;
        digitalWrite(LED_PIN, !digitalRead(LED_PIN));
    }
}

/* ============================================================
 *  Module: led_heartbeat
 *  Description: Blinks the LED briefly to indicate system alive.
 *  Dependencies: None
 * ============================================================ */
static void led_heartbeat_init(void)
{
    /* LED pin already initialized by led_blink_init */
}

static void led_heartbeat_update(void)
{
    static unsigned long last_beat = 0;
    unsigned long now = millis();

    if (now - last_beat >= HEARTBEAT_INTERVAL_MS) {
        last_beat = now;
        /* Short pulse to indicate heartbeat */
        digitalWrite(LED_PIN, HIGH);
        delay(50);
        digitalWrite(LED_PIN, LOW);
    }
}

/* ============================================================
 *  Module: uart_driver
 *  Description: Sends a heartbeat count over UART at 9600 baud.
 *  Dependencies: None
 * ============================================================ */
static unsigned long heartbeat_count = 0;

static void uart_driver_init(void)
{
    Serial.begin(SERIAL_BAUD);
    /* Wait for serial port to stabilize (optional, for USB adapters) */
    delay(100);
    Serial.println("UART Heartbeat Driver Started");
}

static void uart_driver_update(void)
{
    static unsigned long last_send = 0;
    unsigned long now = millis();

    if (now - last_send >= HEARTBEAT_INTERVAL_MS) {
        last_send = now;
        heartbeat_count++;
        Serial.print("HEARTBEAT count# ");
        Serial.println(heartbeat_count);
    }
}

/* ============================================================
 *  Arduino Setup and Loop
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
    /* Update all modules in a non-blocking cooperative manner */
    led_blink_update();
    led_heartbeat_update();
    uart_driver_update();
}