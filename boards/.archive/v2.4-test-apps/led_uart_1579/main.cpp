/*
 * main.c - Arduino UNO R3 (ATmega328P) firmware
 * 
 * Features:
 * 1. LED blinking at 200ms interval
 * 2. UART communication at 9600 baud
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
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=15793616\n";
        for (const char* p = sig; *p; p++) {
            while (!(UCSR0A & (1 << UDRE0))) { }
            UDR0 = (unsigned char)(*p);
        }
    }
} _firmforge_boot;
}

/* ========================================================================== */
/* Module: led_blink                                                          */
/* Description: Controls the built-in LED with a 200ms toggle interval        */
/* ========================================================================== */

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
 * This function toggles the built-in LED and provides a 200ms delay
 * to create a visible blinking pattern.
 */
static void led_blink_update(void)
{
    digitalWrite(LED_BUILTIN, !digitalRead(LED_BUILTIN));
    delay(200);
}

/* ========================================================================== */
/* Module: uart_driver                                                        */
/* Description: Handles UART serial communication at 9600 baud                */
/* ========================================================================== */

/**
 * @brief Initialize UART communication
 * 
 * Configures the serial port with 9600 baud rate, 8 data bits,
 * no parity, and 1 stop bit (8N1).
 */
static void uart_driver_init(void)
{
    Serial.begin(9600);
    
    /* Wait for serial port to stabilize (optional, recommended for USB) */
    while (!Serial) {
        ; /* Wait for serial connection (needed for some boards) */
    }
}

/**
 * @brief Send "HELLO" message over UART
 * 
 * Transmits the string "HELLO" followed by a newline character
 * to the serial console.
 */
static void uart_driver_send_hello(void)
{
    Serial.println("HELLO");
}

/* ========================================================================== */
/* Main Application                                                           */
/* ========================================================================== */

/**
 * @brief Arduino setup function
 * 
 * Called once at startup. Initializes all hardware modules.
 */
void setup(void)
{
    /* Initialize LED blink module */
    led_blink_init();
    
    /* Initialize UART communication */
    uart_driver_init();
}

/**
 * @brief Arduino main loop
 * 
 * Called repeatedly after setup(). Implements the main application logic:
 * - Toggle LED every 200ms
 * - Send "HELLO" message over serial
 */
void loop(void)
{
    /* Update LED blink state (includes 200ms delay) */
    led_blink_update();
    
    /* Send "HELLO" message over UART */
    uart_driver_send_hello();
}