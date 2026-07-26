#include <Arduino.h>
/* FirmForge Boot Signature — AVR UART0 (TX=pin1, 9600) */
namespace {
struct _FirmForgeBoot {
    _FirmForgeBoot() {
        UBRR0H = (unsigned char)(103 >> 8);
        UBRR0L = (unsigned char)(103);
        UCSR0B = (1 << TXEN0);
        UCSR0C = (3 << UCSZ00);
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=710106e1\n";
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
    digitalWrite(LED_BUILTIN, LOW);  // Start with LED off
}

/**
 * @brief Toggle the LED state with 500ms delay
 * 
 * This function toggles the LED and waits 500ms.
 * For non-blocking operation, use millis() instead.
 */
void led_blink_update(void)
{
    static uint8_t led_state = LOW;
    
    // Toggle LED state
    led_state = (led_state == HIGH) ? LOW : HIGH;
    digitalWrite(LED_BUILTIN, led_state);
    
    // 500ms delay (half period = 250ms on, 250ms off)
    delay(250);
}

// ============================================================================
// Module: uart_driver
// Description: Handles UART serial communication at 9600 baud
// ============================================================================

/**
 * @brief Initialize UART serial communication
 * 
 * Configures serial port at 9600 baud, 8 data bits, no parity, 1 stop bit.
 */
void uart_driver_init(void)
{
    Serial.begin(9600);
    
    // Wait for serial port to initialize (optional, for USB-serial adapters)
    // On Arduino UNO, this is not strictly necessary but good practice
    delay(100);
}

/**
 * @brief Send a status message over UART
 * 
 * Prints a simple status string to indicate the system is running.
 */
void uart_driver_send_status(void)
{
    static unsigned long last_print = 0;
    unsigned long now = millis();
    
    // Print status every 1000ms (non-blocking using millis)
    if (now - last_print >= 1000) {
        last_print = now;
        Serial.println("System OK - LED blinking at 500ms");
    }
}

// ============================================================================
// Arduino setup() and loop()
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
    
    // Initial status message
    Serial.println("Arduino UNO R3 starting...");
}

/**
 * @brief Arduino main loop
 * 
 * Called repeatedly. Updates LED blink and UART communication.
 */
void loop(void)
{
    // Update LED blink (blocking delay inside)
    led_blink_update();
    
    // Send UART status (non-blocking)
    uart_driver_send_status();
}