/*
 * main.c - LED Blink and UART Communication for Arduino UNO R3 (ATmega328P)
 * 
 * Features:
 * 1. LED_BUILTIN (pin 13) blinks at 500ms interval
 * 2. Serial communication at 9600 baud, prints status message
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
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=03297a48\n";
        for (const char* p = sig; *p; p++) {
            while (!(UCSR0A & (1 << UDRE0))) { }
            UDR0 = (unsigned char)(*p);
        }
    }
} _firmforge_boot;
}

/* ==========================================================================
 * Module: led_blink
 * Description: Controls the built-in LED with a 500ms blink pattern
 * Dependencies: None
 * ========================================================================== */

/**
 * @brief Initialize the LED pin as an output
 * 
 * Sets the direction of the built-in LED pin to OUTPUT
 * so that digitalWrite can control it.
 */
void led_blink_init(void)
{
    /* Configure LED_BUILTIN (Arduino pin 13) as output */
    pinMode(LED_BUILTIN, OUTPUT);
    
    /* Ensure LED starts in OFF state */
    digitalWrite(LED_BUILTIN, LOW);
}

/**
 * @brief Toggle the LED state
 * 
 * Reads the current state of the LED pin and inverts it.
 * This creates a 50% duty cycle blink when called periodically.
 */
void led_blink_toggle(void)
{
    /* Read current state and invert */
    uint8_t current_state = digitalRead(LED_BUILTIN);
    digitalWrite(LED_BUILTIN, (current_state == HIGH) ? LOW : HIGH);
}

/**
 * @brief Perform one blink cycle with 500ms delay
 * 
 * Toggles the LED and waits for 500 milliseconds.
 * This function blocks execution during the delay.
 */
void led_blink_update(void)
{
    led_blink_toggle();
    delay(500);  /* 500ms delay for blink interval */
}

/* ==========================================================================
 * Module: uart_driver
 * Description: Handles UART serial communication at 9600 baud
 * Dependencies: None
 * ========================================================================== */

/**
 * @brief Initialize UART serial communication
 * 
 * Configures the hardware serial port with:
 * - Baud rate: 9600
 * - Data bits: 8
 * - Parity: None
 * - Stop bits: 1
 */
void uart_driver_init(void)
{
    /* Initialize serial communication at 9600 baud */
    Serial.begin(9600);
    
    /* Wait for serial port to stabilize (optional, for USB-serial adapters) */
    delay(100);
}

/**
 * @brief Send a status message over UART
 * 
 * Prints a formatted message indicating the system is running.
 * Includes the current LED state for debugging.
 */
void uart_driver_send_status(void)
{
    /* Read current LED state */
    uint8_t led_state = digitalRead(LED_BUILTIN);
    
    /* Send status message */
    Serial.print("System running - LED state: ");
    if (led_state == HIGH)
    {
        Serial.println("ON");
    }
    else
    {
        Serial.println("OFF");
    }
}

/* ==========================================================================
 * Main Application
 * Description: Arduino setup() and loop() functions
 * ========================================================================== */

/**
 * @brief Arduino setup function - runs once at startup
 * 
 * Initializes all modules:
 * 1. LED blink module
 * 2. UART communication module
 * 
 * Also sends an initial startup message.
 */
void setup(void)
{
    /* Initialize LED blink module */
    led_blink_init();
    
    /* Initialize UART communication */
    uart_driver_init();
    
    /* Send startup message */
    Serial.println("System initialized - LED Blink + UART Demo");
    Serial.println("Blinking LED at 500ms interval on pin 13");
}

/**
 * @brief Arduino main loop - runs repeatedly
 * 
 * Performs the following tasks each iteration:
 * 1. Toggle LED state with 500ms delay
 * 2. Send status message over UART
 * 
 * The loop runs continuously with a total period of ~500ms
 * (dominated by the delay in led_blink_update).
 */
void loop(void)
{
    /* Update LED blink state (includes 500ms delay) */
    led_blink_update();
    
    /* Send current status over UART */
    uart_driver_send_status();
}