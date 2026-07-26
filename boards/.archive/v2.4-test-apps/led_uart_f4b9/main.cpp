/*
 * main.c - LED Blink and UART Communication for Arduino UNO R3 (ATmega328P)
 * 
 * Features:
 * 1. LED_BUILTIN (pin 13) blinks at 500ms interval
 * 2. Serial communication at 9600 baud, printing status messages
 * 
 * F_CPU: 16MHz
 * Flash: 256KB
 * SRAM: 8KB
 */

#include <Arduino.h>
/* FirmForge Boot Signature — AVR UART0 (TX=pin1, 9600) */
namespace {
struct _FirmForgeBoot {
    _FirmForgeBoot() {
        UBRR0H = (unsigned char)(103 >> 8);
        UBRR0L = (unsigned char)(103);
        UCSR0B = (1 << TXEN0);
        UCSR0C = (3 << UCSZ00);
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=f4b9431f\n";
        for (const char* p = sig; *p; p++) {
            while (!(UCSR0A & (1 << UDRE0))) { }
            UDR0 = (unsigned char)(*p);
        }
    }
} _firmforge_boot;
}

/*============================================================================
 * Module: led_blink
 * Description: Controls the built-in LED blinking at 500ms intervals
 * Dependencies: None
 *============================================================================*/

/**
 * @brief Initialize the LED pin as output
 */
static void led_blink_init(void)
{
    pinMode(LED_BUILTIN, OUTPUT);
    digitalWrite(LED_BUILTIN, LOW);  /* Start with LED off */
}

/**
 * @brief Toggle the LED state
 * 
 * Called periodically to create 500ms blink effect.
 * Uses non-blocking approach with millis() for timing.
 */
static void led_blink_update(void)
{
    static unsigned long last_toggle_time = 0;
    const unsigned long blink_interval = 500;  /* 500ms blink interval */
    
    unsigned long current_time = millis();
    
    if (current_time - last_toggle_time >= blink_interval)
    {
        /* Toggle LED state */
        int current_state = digitalRead(LED_BUILTIN);
        digitalWrite(LED_BUILTIN, !current_state);
        
        last_toggle_time = current_time;
    }
}

/*============================================================================
 * Module: uart_driver
 * Description: Handles UART serial communication at 9600 baud
 * Dependencies: None
 *============================================================================*/

/**
 * @brief Initialize UART serial communication
 * 
 * Configures serial port at 9600 baud rate.
 * Note: Uses Arduino pins 0 (RX) and 1 (TX).
 */
static void uart_driver_init(void)
{
    Serial.begin(9600);
    
    /* Wait for serial port to stabilize (optional, for USB-serial adapters) */
    while (!Serial) {
        ;  /* Wait for serial connection (needed for some boards) */
    }
    
    Serial.println("UART initialized at 9600 baud");
}

/**
 * @brief Send periodic status message over UART
 * 
 * Prints a status message every 2 seconds to indicate system is running.
 */
static void uart_driver_update(void)
{
    static unsigned long last_print_time = 0;
    const unsigned long print_interval = 2000;  /* Print every 2 seconds */
    
    unsigned long current_time = millis();
    
    if (current_time - last_print_time >= print_interval)
    {
        Serial.print("System running... LED state: ");
        if (digitalRead(LED_BUILTIN) == HIGH)
        {
            Serial.println("ON");
        }
        else
        {
            Serial.println("OFF");
        }
        
        last_print_time = current_time;
    }
}

/*============================================================================
 * Main Arduino entry points
 *============================================================================*/

/**
 * @brief Arduino setup function
 * 
 * Initializes all modules:
 * - LED blink module
 * - UART communication module
 */
void setup(void)
{
    /* Initialize all modules */
    led_blink_init();
    uart_driver_init();
    
    Serial.println("System ready - LED blinking at 500ms, UART at 9600 baud");
}

/**
 * @brief Arduino main loop
 * 
 * Continuously updates all modules:
 * - LED blink (500ms toggle)
 * - UART status messages (every 2 seconds)
 */
void loop(void)
{
    /* Update all modules */
    led_blink_update();
    uart_driver_update();
}