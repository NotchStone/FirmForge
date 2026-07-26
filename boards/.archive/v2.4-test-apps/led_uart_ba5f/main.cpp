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
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=ba5ff268\n";
        for (const char* p = sig; *p; p++) {
            while (!(UCSR0A & (1 << UDRE0))) { }
            UDR0 = (unsigned char)(*p);
        }
    }
} _firmforge_boot;
}

/*============================================================================
 * Module: led_blink
 * Description: Controls the built-in LED with 200ms toggle interval
 *============================================================================*/

/**
 * @brief Initialize LED pin as output
 */
static void led_blink_init(void)
{
    pinMode(LED_BUILTIN, OUTPUT);
    digitalWrite(LED_BUILTIN, LOW);  /* Start with LED off */
}

/**
 * @brief Toggle LED state with 200ms delay
 * 
 * This function blocks for 200ms while toggling the LED.
 * For non-blocking operation, consider using millis() based timing.
 */
static void led_blink_update(void)
{
    digitalWrite(LED_BUILTIN, HIGH);  /* Turn LED on */
    delay(200);                       /* Wait 200ms */
    
    digitalWrite(LED_BUILTIN, LOW);   /* Turn LED off */
    delay(200);                       /* Wait 200ms */
}

/*============================================================================
 * Module: uart_driver
 * Description: UART communication at 9600 baud
 *============================================================================*/

/**
 * @brief Initialize UART at 9600 baud
 */
static void uart_driver_init(void)
{
    Serial.begin(9600);
    
    /* Wait for serial port to initialize (optional, for USB adapters) */
    while (!Serial) {
        ;  /* Wait for serial connection (needed for some boards) */
    }
}

/**
 * @brief Send "HELLO" message over UART
 * 
 * Prints the message once per call. Called periodically from loop().
 */
static void uart_driver_send_hello(void)
{
    Serial.println("HELLO");
}

/*============================================================================
 * Main application
 *============================================================================*/

/**
 * @brief Arduino setup function - runs once at startup
 * 
 * Initializes all modules:
 * - LED blinking module
 * - UART communication module
 */
void setup(void)
{
    /* Initialize all modules */
    led_blink_init();
    uart_driver_init();
}

/**
 * @brief Arduino main loop - runs repeatedly
 * 
 * Executes all tasks in sequence:
 * 1. Toggle LED with 200ms delay
 * 2. Send "HELLO" message over UART
 * 
 * Note: The 200ms delay in led_blink_update() also provides
 * timing for the serial message, so it's sent every 400ms.
 */
void loop(void)
{
    /* Task 1: LED blinking at 200ms interval */
    led_blink_update();
    
    /* Task 2: Send HELLO message over UART */
    uart_driver_send_hello();
}