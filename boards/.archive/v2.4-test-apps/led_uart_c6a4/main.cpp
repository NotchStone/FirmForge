#include <Arduino.h>
/* FirmForge Boot Signature — AVR UART0 (TX=pin1, 9600) */
namespace {
struct _FirmForgeBoot {
    _FirmForgeBoot() {
        UBRR0H = (unsigned char)(103 >> 8);
        UBRR0L = (unsigned char)(103);
        UCSR0B = (1 << TXEN0);
        UCSR0C = (3 << UCSZ00);
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=c6a40a00\n";
        for (const char* p = sig; *p; p++) {
            while (!(UCSR0A & (1 << UDRE0))) { }
            UDR0 = (unsigned char)(*p);
        }
    }
} _firmforge_boot;
}

/*
 * LED Blink Task
 * Blinks the built-in LED at 500ms intervals.
 */

// Pin definitions
#define LED_PIN LED_BUILTIN  // Built-in LED on pin 13

// Timing constants
#define BLINK_INTERVAL_MS 500  // Blink interval in milliseconds

// Function prototypes
void led_blink_init(void);
void led_blink_update(void);

/*
 * UART Driver Task
 * Sends "OK" message over serial at regular intervals.
 */

// Serial communication settings
#define SERIAL_BAUD_RATE 9600  // Standard baud rate for serial communication
#define SERIAL_OK_INTERVAL_MS 1000  // Interval for sending "OK" message

// Function prototypes
void uart_driver_init(void);
void uart_driver_update(void);

/*
 * Main Arduino entry point: setup()
 * Initializes all modules.
 */
void setup(void)
{
    // Initialize LED blink module
    led_blink_init();

    // Initialize UART driver module
    uart_driver_init();
}

/*
 * Main Arduino entry point: loop()
 * Runs continuously, updating all modules.
 */
void loop(void)
{
    // Update LED blink module
    led_blink_update();

    // Update UART driver module
    uart_driver_update();
}

/*
 * LED Blink Module Implementation
 */

// State variables for non-blocking LED blink
static unsigned long led_blink_last_toggle_ms = 0;
static uint8_t led_blink_state = LOW;

/*
 * Initialize LED pin as output.
 */
void led_blink_init(void)
{
    pinMode(LED_PIN, OUTPUT);
    digitalWrite(LED_PIN, LOW);  // Start with LED off
}

/*
 * Update LED blink state.
 * Toggles the LED every BLINK_INTERVAL_MS milliseconds.
 */
void led_blink_update(void)
{
    unsigned long current_time = millis();

    // Check if it's time to toggle the LED
    if ((current_time - led_blink_last_toggle_ms) >= BLINK_INTERVAL_MS)
    {
        // Toggle LED state
        led_blink_state = (led_blink_state == HIGH) ? LOW : HIGH;
        digitalWrite(LED_PIN, led_blink_state);

        // Update last toggle timestamp
        led_blink_last_toggle_ms = current_time;
    }
}

/*
 * UART Driver Module Implementation
 */

// State variables for non-blocking serial message
static unsigned long uart_driver_last_send_ms = 0;

/*
 * Initialize UART communication.
 */
void uart_driver_init(void)
{
    Serial.begin(SERIAL_BAUD_RATE);
}

/*
 * Update UART driver state.
 * Sends "OK" message over serial every SERIAL_OK_INTERVAL_MS milliseconds.
 */
void uart_driver_update(void)
{
    unsigned long current_time = millis();

    // Check if it's time to send the "OK" message
    if ((current_time - uart_driver_last_send_ms) >= SERIAL_OK_INTERVAL_MS)
    {
        Serial.println("OK");

        // Update last send timestamp
        uart_driver_last_send_ms = current_time;
    }
}