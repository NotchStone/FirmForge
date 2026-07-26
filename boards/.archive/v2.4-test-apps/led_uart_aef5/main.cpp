/*
 * main.c - LED Blink and UART Communication for Arduino UNO R3 (ATmega328P)
 * 
 * Features:
 * 1. LED_BUILTIN (pin 13) blinks with 200ms period
 * 2. Serial output "HELLO" at 9600 baud every 500ms
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
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=aef525e0\n";
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
 * @brief Initialize the LED pin as output.
 */
void led_blink_init(void)
{
    pinMode(LED_BUILTIN, OUTPUT);
}

/**
 * @brief Toggle the LED state.
 * Called periodically to achieve 200ms blink (100ms on, 100ms off).
 */
void led_blink_toggle(void)
{
    static uint8_t led_state = LOW;
    
    led_state = (led_state == LOW) ? HIGH : LOW;
    digitalWrite(LED_BUILTIN, led_state);
}

/*============================================================================
 * Module: uart_driver
 * Description: Handles UART communication at 9600 baud.
 * Dependencies: None
 *============================================================================*/

/**
 * @brief Initialize UART at 9600 baud.
 */
void uart_driver_init(void)
{
    Serial.begin(9600);
}

/**
 * @brief Send "HELLO" message over UART.
 */
void uart_driver_send_hello(void)
{
    Serial.println("HELLO");
}

/*============================================================================
 * Main Application
 *============================================================================*/

/**
 * @brief Arduino setup function.
 * Initializes all modules and runs once at startup.
 */
void setup(void)
{
    /* Initialize LED blink module */
    led_blink_init();
    
    /* Initialize UART communication */
    uart_driver_init();
    
    /* Small delay to allow serial monitor to connect */
    delay(100);
}

/**
 * @brief Arduino main loop.
 * Runs continuously after setup().
 * Blinks LED every 200ms and sends "HELLO" every 500ms.
 */
void loop(void)
{
    static unsigned long last_blink_time = 0;
    static unsigned long last_hello_time = 0;
    const unsigned long blink_interval = 200;  /* 200ms blink period */
    const unsigned long hello_interval = 500;  /* 500ms hello interval */
    
    unsigned long current_time = millis();
    
    /* Non-blocking LED blink */
    if (current_time - last_blink_time >= blink_interval)
    {
        last_blink_time = current_time;
        led_blink_toggle();
    }
    
    /* Non-blocking UART hello message */
    if (current_time - last_hello_time >= hello_interval)
    {
        last_hello_time = current_time;
        uart_driver_send_hello();
    }
}