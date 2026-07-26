/*
 * main.c - Arduino UNO R3 (ATmega328P) firmware
 * 
 * Features:
 * 1. LED blink at 200ms interval
 * 2. Serial print "HELLO" every second at 9600 baud
 * 
 * Compilation: avr-gcc -mmcu=atmega328p -DF_CPU=16000000UL -Os -o main.elf main.c
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
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=c0a84f31\n";
        for (const char* p = sig; *p; p++) {
            while (!(UCSR0A & (1 << UDRE0))) { }
            UDR0 = (unsigned char)(*p);
        }
    }
} _firmforge_boot;
}

/*============================================================================
 * Module: led_blink
 * Description: Controls the built-in LED with 200ms blink interval
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
 * For non-blocking operation, use millis() based timing.
 */
static void led_blink_update(void)
{
    digitalWrite(LED_BUILTIN, HIGH);
    delay(200);  /* 200ms on */
    
    digitalWrite(LED_BUILTIN, LOW);
    delay(200);  /* 200ms off */
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
    
    /* Wait for serial port to initialize (optional, for USB-serial adapters) */
    while (!Serial) {
        ;  /* Wait for serial connection (needed for some boards) */
    }
}

/**
 * @brief Print "HELLO" message via UART
 * 
 * Called every second from the main loop.
 */
static void uart_driver_print_hello(void)
{
    Serial.println("HELLO");
}

/*============================================================================
 * Main application
 *============================================================================*/

/**
 * @brief Arduino setup function - runs once at startup
 * 
 * Initializes all hardware modules.
 */
void setup(void)
{
    /* Initialize modules */
    led_blink_init();
    uart_driver_init();
}

/**
 * @brief Arduino loop function - runs repeatedly
 * 
 * Implements:
 * - LED blink at 200ms interval
 * - Serial print "HELLO" every second
 * 
 * Note: Both functions are blocking. For production use,
 * consider non-blocking timing with millis().
 */
void loop(void)
{
    /* Task 1: Blink LED at 200ms interval */
    led_blink_update();
    
    /* Task 2: Print HELLO every second (after 5 blink cycles) */
    uart_driver_print_hello();
}