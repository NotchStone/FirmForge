/*
 * main.c - LED Blink and UART Communication for Arduino UNO R3 (ATmega328P)
 * 
 * Features:
 * 1. LED_BUILTIN (pin 13) blinks at 500ms interval
 * 2. Serial communication at 9600 baud, prints status messages
 * 
 * Compilation: avr-gcc -mmcu=atmega328p -DF_CPU=16000000UL -Os -o main.elf main.c
 * 
 * Hardware: Arduino UNO R3, ATmega328P @ 16MHz
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
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=14cfe0f5\n";
        for (const char* p = sig; *p; p++) {
            while (!(UCSR0A & (1 << UDRE0))) { }
            UDR0 = (unsigned char)(*p);
        }
    }
} _firmforge_boot;
}

/*============================================================================
 * Module: led_blink
 * Description: Controls the built-in LED with 500ms blink interval
 * Dependencies: None
 *============================================================================*/

/**
 * @brief Initialize the LED pin as output
 */
static void led_blink_init(void)
{
    pinMode(LED_BUILTIN, OUTPUT);
    digitalWrite(LED_BUILTIN, LOW);  /* Start with LED off */
}

/**
 * @brief Toggle the LED state
 *        Called every 500ms to create blink effect
 */
static void led_blink_update(void)
{
    static uint8_t led_state = LOW;
    
    led_state = (led_state == LOW) ? HIGH : LOW;
    digitalWrite(LED_BUILTIN, led_state);
}

/*============================================================================
 * Module: uart_driver
 * Description: UART communication at 9600 baud
 * Dependencies: None
 *============================================================================*/

/**
 * @brief Initialize UART at 9600 baud
 *        Uses Arduino Serial API (USART0 on pins 0/1)
 */
static void uart_driver_init(void)
{
    Serial.begin(9600);
    
    /* Wait for serial port to initialize (optional, for USB-serial adapters) */
    delay(100);
    
    Serial.println("System initialized at 9600 baud");
}

/**
 * @brief Print a status message with current blink count
 * 
 * @param blink_count Number of blinks since startup
 */
static void uart_driver_print_status(uint16_t blink_count)
{
    Serial.print("Blink count: ");
    Serial.println(blink_count);
}

/*============================================================================
 * Main Application
 *============================================================================*/

/* Application constants */
#define BLINK_INTERVAL_MS   500u    /* LED blink interval in milliseconds */
#define STATUS_INTERVAL_MS  2000u   /* Serial status print interval */

/* Application state */
static uint16_t blink_counter = 0;  /* Number of blinks since startup */
static unsigned long last_blink_time = 0;
static unsigned long last_status_time = 0;

/**
 * @brief Arduino setup function - runs once at startup
 *        Initializes all modules
 */
void setup(void)
{
    /* Initialize modules */
    led_blink_init();
    uart_driver_init();
    
    /* Initialize timing variables */
    last_blink_time = millis();
    last_status_time = millis();
    
    Serial.println("LED Blink + UART Demo started");
}

/**
 * @brief Arduino loop function - runs repeatedly
 *        Handles LED blinking and periodic status updates
 */
void loop(void)
{
    unsigned long current_time = millis();
    
    /* Task 1: LED Blink - toggle every BLINK_INTERVAL_MS */
    if ((current_time - last_blink_time) >= BLINK_INTERVAL_MS)
    {
        last_blink_time = current_time;
        led_blink_update();
        blink_counter++;
    }
    
    /* Task 2: UART Status - print status every STATUS_INTERVAL_MS */
    if ((current_time - last_status_time) >= STATUS_INTERVAL_MS)
    {
        last_status_time = current_time;
        uart_driver_print_status(blink_counter);
    }
    
    /* Small delay to prevent tight loop (optional, improves stability) */
    delay(1);
}