#include <Arduino.h>
/* FirmForge Boot Signature — AVR UART0 (TX=pin1, 9600) */
namespace {
struct _FirmForgeBoot {
    _FirmForgeBoot() {
        UBRR0H = (unsigned char)(103 >> 8);
        UBRR0L = (unsigned char)(103);
        UCSR0B = (1 << TXEN0);
        UCSR0C = (3 << UCSZ00);
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=e563dcdb\n";
        for (const char* p = sig; *p; p++) {
            while (!(UCSR0A & (1 << UDRE0))) { }
            UDR0 = (unsigned char)(*p);
        }
    }
} _firmforge_boot;
}

/*
 * main.c - Arduino UNO R3 (ATmega328P) firmware
 * 
 * Features:
 * 1. LED blink on built-in LED (pin 13) with 500ms period
 * 2. UART communication at 9600 baud, printing status messages
 */

// ============================================================================
// Module: led_blink
// Description: Controls the built-in LED with a 500ms blink period
// ============================================================================

/**
 * @brief Initialize the LED pin as output
 */
static void led_blink_init(void)
{
    pinMode(LED_BUILTIN, OUTPUT);
    digitalWrite(LED_BUILTIN, LOW);
}

/**
 * @brief Toggle the LED state
 * 
 * This function toggles the built-in LED and prints status to serial.
 * Called every 500ms from the main loop.
 */
static void led_blink_toggle(void)
{
    static uint8_t led_state = LOW;
    
    led_state = (led_state == HIGH) ? LOW : HIGH;
    digitalWrite(LED_BUILTIN, led_state);
    
    Serial.print("LED is now ");
    Serial.println(led_state == HIGH ? "ON" : "OFF");
}

// ============================================================================
// Module: uart_driver
// Description: Initializes and manages UART serial communication
// ============================================================================

/**
 * @brief Initialize UART at 9600 baud
 * 
 * Standard baud rate for Arduino UNO R3 serial communication.
 */
static void uart_driver_init(void)
{
    Serial.begin(9600);
    
    // Wait for serial port to connect (needed for some USB-to-serial adapters)
    while (!Serial) {
        ; // Wait for serial connection
    }
    
    Serial.println("UART initialized at 9600 baud");
}

/**
 * @brief Print a status message over UART
 * 
 * @param message Pointer to null-terminated string to send
 */
static void uart_driver_print(const char* message)
{
    Serial.print(message);
}

// ============================================================================
// Main Arduino functions: setup() and loop()
// ============================================================================

/**
 * @brief Arduino setup function
 * 
 * Called once at startup. Initializes all modules.
 */
void setup(void)
{
    // Initialize UART first so we can print debug messages
    uart_driver_init();
    
    // Initialize LED blink module
    led_blink_init();
    
    // Print startup message
    uart_driver_print("System initialized. Starting main loop...\n");
}

/**
 * @brief Arduino main loop function
 * 
 * Called repeatedly after setup(). Implements the 500ms LED blink.
 */
void loop(void)
{
    static unsigned long last_blink_time = 0;
    const unsigned long blink_interval = 500; // 500ms blink period
    
    unsigned long current_time = millis();
    
    // Non-blocking blink: check if 500ms has elapsed
    if (current_time - last_blink_time >= blink_interval) {
        last_blink_time = current_time;
        
        // Toggle the LED and print status
        led_blink_toggle();
    }
    
    // Small delay to prevent tight loop from consuming all CPU
    // This is acceptable for this simple application
    delay(10);
}