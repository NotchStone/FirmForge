// main.c - LED Blink and UART Communication for Arduino UNO R3 (ATmega328P)
// Features:
//   1. LED_BUILTIN blinks every 500ms
//   2. Serial prints "OK" every 1 second at 9600 baud
// Compilation: avr-gcc -mmcu=atmega328p -DF_CPU=16000000UL -Os -o main.elf main.c

#include <Arduino.h>
/* FirmForge Boot Signature — AVR UART0 (TX=pin1, 9600) */
namespace {
struct _FirmForgeBoot {
    _FirmForgeBoot() {
        UBRR0H = (unsigned char)(103 >> 8);
        UBRR0L = (unsigned char)(103);
        UCSR0B = (1 << TXEN0);
        UCSR0C = (3 << UCSZ00);
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=95113ec2\n";
        for (const char* p = sig; *p; p++) {
            while (!(UCSR0A & (1 << UDRE0))) { }
            UDR0 = (unsigned char)(*p);
        }
    }
} _firmforge_boot;
}

// -----------------------------------------------------------------------------
// Module: led_blink
// -----------------------------------------------------------------------------

/**
 * @brief Initialize the built-in LED pin as output.
 */
void led_blink_init(void)
{
    pinMode(LED_BUILTIN, OUTPUT);
}

/**
 * @brief Toggle the built-in LED state.
 */
void led_blink_toggle(void)
{
    static uint8_t led_state = LOW;
    led_state = (led_state == LOW) ? HIGH : LOW;
    digitalWrite(LED_BUILTIN, led_state);
}

// -----------------------------------------------------------------------------
// Module: uart_driver
// -----------------------------------------------------------------------------

/**
 * @brief Initialize UART communication at 9600 baud.
 */
void uart_driver_init(void)
{
    Serial.begin(9600);
}

/**
 * @brief Print "OK" message over UART.
 */
void uart_driver_print_ok(void)
{
    Serial.println("OK");
}

// -----------------------------------------------------------------------------
// Main Arduino entry points
// -----------------------------------------------------------------------------

/**
 * @brief Arduino setup function.
 *        Initializes LED and UART modules.
 */
void setup(void)
{
    led_blink_init();
    uart_driver_init();
}

/**
 * @brief Arduino main loop.
 *        Blinks LED every 500ms and prints "OK" every 1 second.
 *        Uses non-blocking timing with millis().
 */
void loop(void)
{
    // Timing variables (static to retain values between loop calls)
    static unsigned long last_blink_time = 0;
    static unsigned long last_print_time = 0;

    const unsigned long current_time = millis();

    // Blink LED every 500ms
    if (current_time - last_blink_time >= 500)
    {
        last_blink_time = current_time;
        led_blink_toggle();
    }

    // Print "OK" every 1000ms
    if (current_time - last_print_time >= 1000)
    {
        last_print_time = current_time;
        uart_driver_print_ok();
    }
}