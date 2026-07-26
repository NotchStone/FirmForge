/*
 * main.c - Arduino UNO R3 (ATmega328P) firmware
 * 
 * Features:
 * 1. LED blinking at 200ms interval on built-in LED (pin 13)
 * 2. Serial communication at 9600 baud, printing "HELLO" periodically
 *
 * Compilation: avr-gcc -mmcu=atmega328p -DF_CPU=16000000UL -Os -o main.elf main.c
 * Programming: avrdude -c arduino -p m328p -P /dev/ttyACM0 -U flash:w:main.elf
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
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=d2b7c649\n";
        for (const char* p = sig; *p; p++) {
            while (!(UCSR0A & (1 << UDRE0))) { }
            UDR0 = (unsigned char)(*p);
        }
    }
} _firmforge_boot;
}

/*============================================================================
 * Module: led_blink
 * Description: Controls the built-in LED with a 200ms blink period.
 * Dependencies: None
 *============================================================================*/

/**
 * @brief Initialize the LED pin as an output.
 */
static void led_blink_init(void)
{
    pinMode(LED_BUILTIN, OUTPUT);
    digitalWrite(LED_BUILTIN, LOW);  /* Start with LED off */
}

/**
 * @brief Toggle the LED state. Called periodically to achieve 200ms blink.
 *        Each call toggles the LED; call every 200ms for 50% duty cycle.
 */
static void led_blink_toggle(void)
{
    static uint8_t led_state = LOW;
    led_state = (led_state == LOW) ? HIGH : LOW;
    digitalWrite(LED_BUILTIN, led_state);
}

/*============================================================================
 * Module: uart_driver
 * Description: Provides serial communication at 9600 baud.
 * Dependencies: None
 *============================================================================*/

/**
 * @brief Initialize UART at 9600 baud.
 */
static void uart_driver_init(void)
{
    Serial.begin(9600);
    /* Allow time for serial monitor to connect */
    delay(100);
}

/**
 * @brief Send "HELLO" message over UART.
 */
static void uart_driver_send_hello(void)
{
    Serial.println("HELLO");
}

/*============================================================================
 * Main application: setup() and loop()
 *============================================================================*/

/**
 * @brief Arduino setup function. Called once at startup.
 *        Initializes all modules.
 */
void setup(void)
{
    led_blink_init();
    uart_driver_init();
}

/**
 * @brief Arduino main loop. Called repeatedly.
 *        Blinks LED every 200ms and prints "HELLO" every 200ms.
 */
void loop(void)
{
    /* Blink LED with 200ms period (100ms on, 100ms off) */
    led_blink_toggle();
    
    /* Send HELLO message over serial */
    uart_driver_send_hello();
    
    /* Wait 200ms before next iteration */
    delay(200);
}