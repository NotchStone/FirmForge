/*
 * main.c - LED Blink and UART Communication for Arduino UNO R3 (ATmega328P)
 * 
 * Features:
 * 1. LED_BUILTIN (pin 13) blinks at 500ms interval
 * 2. Serial communication at 9600 baud, prints status messages
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
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=c4c0e986\n";
        for (const char* p = sig; *p; p++) {
            while (!(UCSR0A & (1 << UDRE0))) { }
            UDR0 = (unsigned char)(*p);
        }
    }
} _firmforge_boot;
}

/* ==========================================================================
 * Module: led_blink
 * Description: Controls the built-in LED with a 500ms blink period
 * Dependencies: None
 * ========================================================================== */

/* LED blink interval in milliseconds */
#define LED_BLINK_INTERVAL_MS  500U

/* Non-blocking timing variables for LED blink */
static unsigned long led_previous_millis = 0U;
static uint8_t led_state = LOW;

/**
 * @brief Initialize the LED pin as output
 */
static void led_blink_init(void)
{
    pinMode(LED_BUILTIN, OUTPUT);
    digitalWrite(LED_BUILTIN, LOW);
}

/**
 * @brief Update LED state based on elapsed time (non-blocking)
 * 
 * This function should be called repeatedly from the main loop.
 * It toggles the LED every LED_BLINK_INTERVAL_MS milliseconds.
 */
static void led_blink_update(void)
{
    unsigned long current_millis = millis();
    
    if ((current_millis - led_previous_millis) >= LED_BLINK_INTERVAL_MS)
    {
        led_previous_millis = current_millis;
        
        /* Toggle LED state */
        led_state = (led_state == HIGH) ? LOW : HIGH;
        digitalWrite(LED_BUILTIN, led_state);
    }
}

/* ==========================================================================
 * Module: uart_driver
 * Description: Handles UART serial communication at 9600 baud
 * Dependencies: None
 * ========================================================================== */

/* Serial baud rate */
#define SERIAL_BAUD_RATE  9600UL

/* Status message strings stored in flash (PROGMEM) to save RAM */
static const char str_startup[] PROGMEM = "System started. LED blinking at 500ms.";
static const char str_led_on[]  PROGMEM = "LED ON";
static const char str_led_off[] PROGMEM = "LED OFF";

/**
 * @brief Initialize UART serial communication
 */
static void uart_driver_init(void)
{
    Serial.begin(SERIAL_BAUD_RATE);
    
    /* Wait for serial port to connect (needed for some boards, safe to keep) */
    while (!Serial)
    {
        ; /* Wait for serial connection */
    }
    
    /* Print startup message from flash */
    Serial.println(reinterpret_cast<const __FlashStringHelper*>(str_startup));
}

/**
 * @brief Print LED state change over UART
 * 
 * @param new_state Current LED state (HIGH or LOW)
 */
static void uart_driver_report_led_state(uint8_t new_state)
{
    if (new_state == HIGH)
    {
        Serial.println(reinterpret_cast<const __FlashStringHelper*>(str_led_on));
    }
    else
    {
        Serial.println(reinterpret_cast<const __FlashStringHelper*>(str_led_off));
    }
}

/* ==========================================================================
 * Arduino entry points: setup() and loop()
 * ========================================================================== */

/**
 * @brief Arduino setup function - runs once at startup
 * 
 * Initializes all modules:
 * - LED blink module
 * - UART serial communication
 */
void setup(void)
{
    /* Initialize modules */
    led_blink_init();
    uart_driver_init();
}

/**
 * @brief Arduino main loop - runs repeatedly
 * 
 * Updates LED blink state and reports changes via UART.
 * Uses non-blocking timing with millis() for LED control.
 */
void loop(void)
{
    static uint8_t last_led_state = LOW;
    
    /* Update LED blink */
    led_blink_update();
    
    /* Report LED state changes over UART */
    if (led_state != last_led_state)
    {
        last_led_state = led_state;
        uart_driver_report_led_state(led_state);
    }
}