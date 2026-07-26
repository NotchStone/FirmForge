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
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=2374412b\n";
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
void led_blink_init(void)
{
    pinMode(LED_BUILTIN, OUTPUT);
    digitalWrite(LED_BUILTIN, LOW);  /* Start with LED off */
}

/**
 * @brief Toggle LED state with 200ms delay
 * 
 * This function blocks for 200ms while toggling the LED.
 * For non-blocking operation, consider using millis() timer.
 */
void led_blink_update(void)
{
    static uint8_t led_state = LOW;
    
    /* Toggle LED state */
    led_state = (led_state == LOW) ? HIGH : LOW;
    digitalWrite(LED_BUILTIN, led_state);
    
    /* Wait 200ms for blink interval */
    delay(200);
}

/*============================================================================
 * Module: uart_driver
 * Description: UART communication at 9600 baud
 *============================================================================*/

/**
 * @brief Initialize UART at 9600 baud
 */
void uart_driver_init(void)
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
 * Called every second from main loop.
 */
void uart_driver_print_hello(void)
{
    Serial.println("HELLO");
}

/*============================================================================
 * Main application
 *============================================================================*/

/**
 * @brief Arduino setup function - runs once at startup
 * 
 * Initializes all modules and hardware peripherals.
 */
void setup(void)
{
    /* Initialize all functional modules */
    led_blink_init();
    uart_driver_init();
}

/**
 * @brief Arduino main loop - runs repeatedly
 * 
 * Implements the two main functions:
 * - LED blinks every 200ms
 * - Serial prints "HELLO" every second
 * 
 * Timing is managed using millis() for non-blocking operation.
 */
void loop(void)
{
    static unsigned long last_blink_time = 0;
    static unsigned long last_print_time = 0;
    const unsigned long blink_interval = 200;   /* 200ms blink interval */
    const unsigned long print_interval = 1000;  /* 1 second print interval */
    
    unsigned long current_time = millis();
    
    /* Task 1: LED blink at 200ms interval */
    if (current_time - last_blink_time >= blink_interval) {
        last_blink_time = current_time;
        
        /* Toggle LED state */
        static uint8_t led_state = LOW;
        led_state = (led_state == LOW) ? HIGH : LOW;
        digitalWrite(LED_BUILTIN, led_state);
    }
    
    /* Task 2: Serial print "HELLO" every second */
    if (current_time - last_print_time >= print_interval) {
        last_print_time = current_time;
        Serial.println("HELLO");
    }
}