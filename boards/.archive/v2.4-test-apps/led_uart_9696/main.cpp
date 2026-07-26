#include <Arduino.h>
/* FirmForge Boot Signature — AVR UART0 (TX=pin1, 9600) */
namespace {
struct _FirmForgeBoot {
    _FirmForgeBoot() {
        UBRR0H = (unsigned char)(103 >> 8);
        UBRR0L = (unsigned char)(103);
        UCSR0B = (1 << TXEN0);
        UCSR0C = (3 << UCSZ00);
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=96967851\n";
        for (const char* p = sig; *p; p++) {
            while (!(UCSR0A & (1 << UDRE0))) { }
            UDR0 = (unsigned char)(*p);
        }
    }
} _firmforge_boot;
}

/*
 * main.c - Arduino UNO R3 (ATmega328P) firmware
 * 
 * Features:
 * 1. LED blink on built-in LED (pin 13) with 500ms period
 * 2. UART communication at 115200 baud
 * 
 * Hardware:
 * - MCU: ATmega328P @ 16MHz
 * - LED_BUILTIN: Arduino pin 13 (PB7)
 * - Serial: RX=pin 0, TX=pin 1
 */

/*============================================================================
 * Module: led_blink
 * Description: Blinks the built-in LED at 500ms interval
 *============================================================================*/

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
 */
static void led_blink_toggle(void)
{
    static uint8_t led_state = LOW;
    
    led_state = (led_state == LOW) ? HIGH : LOW;
    digitalWrite(LED_BUILTIN, led_state);
}

/**
 * @brief Update LED blink state - call every 500ms
 */
static void led_blink_update(void)
{
    led_blink_toggle();
}

/*============================================================================
 * Module: uart_driver
 * Description: UART communication at 115200 baud
 *============================================================================*/

/**
 * @brief Initialize UART at 115200 baud
 */
static void uart_driver_init(void)
{
    Serial.begin(115200);
    
    /* Wait for serial port to initialize (optional, for USB-serial adapters) */
    while (!Serial) {
        ; /* Wait for serial connection (needed for some boards) */
    }
}

/**
 * @brief Send a status message over UART
 */
static void uart_driver_send_status(void)
{
    static unsigned long last_print = 0;
    unsigned long now = millis();
    
    /* Print status every 1000ms */
    if (now - last_print >= 1000) {
        last_print = now;
        Serial.println("OK");
    }
}

/**
 * @brief Process any incoming UART data
 */
static void uart_driver_process(void)
{
    if (Serial.available() > 0) {
        char incoming = Serial.read();
        
        /* Echo received character back */
        Serial.print("Echo: ");
        Serial.println(incoming);
    }
}

/*============================================================================
 * Main application
 *============================================================================*/

/**
 * @brief Arduino setup function - runs once at startup
 */
void setup(void)
{
    /* Initialize all modules */
    led_blink_init();
    uart_driver_init();
    
    /* Set unused pins to safe state (INPUT_PULLUP) */
    /* Pins 2-12, A0-A5 are unused - set to INPUT_PULLUP */
    for (uint8_t pin = 2; pin <= 12; pin++) {
        pinMode(pin, INPUT_PULLUP);
    }
    for (uint8_t pin = A0; pin <= A5; pin++) {
        pinMode(pin, INPUT_PULLUP);
    }
}

/**
 * @brief Arduino loop function - runs repeatedly
 */
void loop(void)
{
    static unsigned long last_blink = 0;
    unsigned long now = millis();
    
    /* Update LED blink every 500ms (non-blocking) */
    if (now - last_blink >= 500) {
        last_blink = now;
        led_blink_update();
    }
    
    /* Handle UART communication */
    uart_driver_send_status();
    uart_driver_process();
}