#include <Arduino.h>
/* FirmForge Boot Signature — AVR UART0 (TX=pin1, 9600) */
namespace {
struct _FirmForgeBoot {
    _FirmForgeBoot() {
        UBRR0H = (unsigned char)(103 >> 8);
        UBRR0L = (unsigned char)(103);
        UCSR0B = (1 << TXEN0);
        UCSR0C = (3 << UCSZ00);
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=c6fbd97d\n";
        for (const char* p = sig; *p; p++) {
            while (!(UCSR0A & (1 << UDRE0))) { }
            UDR0 = (unsigned char)(*p);
        }
    }
} _firmforge_boot;
}

/*
 * main.c - LED blink and UART communication for Arduino UNO R3 (ATmega328P)
 * 
 * Features:
 * 1. LED_BUILTIN (pin 13) blinks with 500ms period
 * 2. Serial communication at 9600 baud, prints status message
 */

// ============================================================================
// Module: led_blink
// Description: Controls the built-in LED with a 500ms blink cycle
// ============================================================================

/**
 * @brief Initialize the LED pin as output
 */
void led_blink_init(void)
{
    pinMode(LED_BUILTIN, OUTPUT);
}

/**
 * @brief Toggle the LED state with 500ms delay
 * 
 * This function toggles the LED and waits 500ms.
 * Called repeatedly from loop() to create a continuous blink.
 */
void led_blink_update(void)
{
    static uint8_t led_state = LOW;

    // Toggle LED state
    led_state = (led_state == HIGH) ? LOW : HIGH;
    digitalWrite(LED_BUILTIN, led_state);

    // Wait 500ms for the blink period
    delay(500);
}

// ============================================================================
// Module: uart_driver
// Description: Handles UART serial communication at 9600 baud
// ============================================================================

/**
 * @brief Initialize UART serial communication
 * 
 * Configures Serial at 9600 baud rate.
 * Prints a startup message to confirm communication.
 */
void uart_driver_init(void)
{
    Serial.begin(9600);

    // Wait for serial port to connect (needed for some boards)
    delay(100);

    // Print startup message
    Serial.println("System initialized. UART communication OK.");
}

/**
 * @brief Print a periodic status message over UART
 * 
 * This function prints a message every time it's called.
 * In loop(), it's called once per blink cycle.
 */
void uart_driver_update(void)
{
    Serial.println("LED blink cycle completed.");
}

// ============================================================================
// Main Arduino entry points: setup() and loop()
// ============================================================================

/**
 * @brief Arduino setup function
 * 
 * Called once at startup. Initializes all modules.
 */
void setup(void)
{
    // Initialize modules
    led_blink_init();
    uart_driver_init();
}

/**
 * @brief Arduino main loop
 * 
 * Called repeatedly after setup(). Runs the blink and UART tasks.
 */
void loop(void)
{
    // Update LED blink (500ms delay inside)
    led_blink_update();

    // Update UART communication
    uart_driver_update();
}