/*
 * main.c - LED Blink and UART Communication for Arduino UNO R3 (ATmega328P)
 * 
 * Features:
 * 1. LED_BUILTIN (pin 13) blinks at 200ms interval
 * 2. Serial prints "HELLO" at 9600 baud rate
 * 
 * F_CPU: 16MHz
 * Compiler: avr-gcc with Arduino core
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
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=bd76ab27\n";
        for (const char* p = sig; *p; p++) {
            while (!(UCSR0A & (1 << UDRE0))) { }
            UDR0 = (unsigned char)(*p);
        }
    }
} _firmforge_boot;
}

/*============================================================================
 * Module: led_blink
 * Description: Controls the built-in LED with a 200ms blink interval
 * Dependencies: None
 *============================================================================*/

/**
 * @brief Initialize the LED pin as output
 */
void led_blink_init(void)
{
    pinMode(LED_BUILTIN, OUTPUT);
}

/**
 * @brief Toggle the LED state with 200ms delay
 * 
 * This function toggles the built-in LED and waits for 200ms.
 * The delay is blocking, suitable for simple demo purposes.
 */
void led_blink_update(void)
{
    digitalWrite(LED_BUILTIN, HIGH);
    delay(200);
    digitalWrite(LED_BUILTIN, LOW);
    delay(200);
}

/*============================================================================
 * Module: uart_driver
 * Description: Handles UART communication at 9600 baud
 * Dependencies: None
 *============================================================================*/

/**
 * @brief Initialize UART at 9600 baud rate
 * 
 * Uses Arduino Serial API to configure USART0 (RX=pin 0, TX=pin 1)
 */
void uart_driver_init(void)
{
    Serial.begin(9600);
}

/**
 * @brief Send "HELLO" message over UART
 * 
 * Prints the string followed by a newline for readability.
 */
void uart_driver_send_hello(void)
{
    Serial.println("HELLO");
}

/*============================================================================
 * Main Arduino Functions
 *============================================================================*/

/**
 * @brief Arduino setup function
 * 
 * Called once at startup. Initializes all modules.
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
 * Called repeatedly. Blinks LED and sends HELLO message.
 */
void loop(void)
{
    /* Update LED blink state */
    led_blink_update();
    
    /* Send HELLO message over serial */
    uart_driver_send_hello();
}