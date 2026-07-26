#include <Arduino.h>
/* FirmForge Boot Signature — AVR UART0 (TX=pin1, 9600) */
namespace {
struct _FirmForgeBoot {
    _FirmForgeBoot() {
        UBRR0H = (unsigned char)(103 >> 8);
        UBRR0L = (unsigned char)(103);
        UCSR0B = (1 << TXEN0);
        UCSR0C = (3 << UCSZ00);
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=9ba94e11\n";
        for (const char* p = sig; *p; p++) {
            while (!(UCSR0A & (1 << UDRE0))) { }
            UDR0 = (unsigned char)(*p);
        }
    }
} _firmforge_boot;
}

/*
 * LED Blink Task
 * Blinks the built-in LED with a 500ms period (250ms on, 250ms off).
 */

// Pin definitions
#define LED_PIN LED_BUILTIN  // Built-in LED on pin 13

// Timing constants
#define LED_BLINK_INTERVAL_MS 250  // 250ms on/off for 500ms period

// Function prototypes
void led_blink_init(void);
void led_blink_update(void);

// State variables
static unsigned long last_led_toggle_ms = 0;
static bool led_state = LOW;

/*
 * Initialize the LED pin as an output.
 */
void led_blink_init(void) {
    pinMode(LED_PIN, OUTPUT);
    digitalWrite(LED_PIN, LOW);
}

/*
 * Non-blocking LED blink update.
 * Toggles the LED every LED_BLINK_INTERVAL_MS milliseconds.
 */
void led_blink_update(void) {
    unsigned long current_ms = millis();
    if (current_ms - last_led_toggle_ms >= LED_BLINK_INTERVAL_MS) {
        last_led_toggle_ms = current_ms;
        led_state = !led_state;
        digitalWrite(LED_PIN, led_state);
    }
}

/*
 * UART Communication Task
 * Prints "HELLO" every 1 second over serial at 9600 baud.
 */

// Timing constants
#define SERIAL_PRINT_INTERVAL_MS 1000  // Print every 1 second

// Function prototypes
void uart_driver_init(void);
void uart_driver_update(void);

// State variables
static unsigned long last_serial_print_ms = 0;

/*
 * Initialize UART communication at 9600 baud.
 */
void uart_driver_init(void) {
    Serial.begin(9600);
}

/*
 * Non-blocking serial print update.
 * Prints "HELLO" every SERIAL_PRINT_INTERVAL_MS milliseconds.
 */
void uart_driver_update(void) {
    unsigned long current_ms = millis();
    if (current_ms - last_serial_print_ms >= SERIAL_PRINT_INTERVAL_MS) {
        last_serial_print_ms = current_ms;
        Serial.println("HELLO");
    }
}

/*
 * Arduino setup function.
 * Initializes all modules.
 */
void setup(void) {
    led_blink_init();
    uart_driver_init();
}

/*
 * Arduino main loop function.
 * Runs all tasks in a non-blocking manner.
 */
void loop(void) {
    led_blink_update();
    uart_driver_update();
}