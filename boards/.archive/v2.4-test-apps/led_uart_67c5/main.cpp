/*
 * main.c - LED blink and UART communication for Arduino UNO R3 (ATmega328P)
 * 
 * Features:
 * 1. LED_BUILTIN (pin 13) blinks with 200ms period
 * 2. Serial prints "HELLO" at 9600 baud every 2 seconds
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
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=67c59fed\n";
        for (const char* p = sig; *p; p++) {
            while (!(UCSR0A & (1 << UDRE0))) { }
            UDR0 = (unsigned char)(*p);
        }
    }
} _firmforge_boot;
}

/* ========================================================================== */
/* Module: led_blink                                                          */
/* Description: Controls the built-in LED with a 200ms blink period           */
/* ========================================================================== */

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
 * This function toggles the LED and waits 200ms.
 * Called repeatedly from loop() to achieve continuous blinking.
 */
void led_blink_update(void)
{
    digitalWrite(LED_BUILTIN, HIGH);
    delay(100);  /* 100ms on */
    digitalWrite(LED_BUILTIN, LOW);
    delay(100);  /* 100ms off */
}

/* ========================================================================== */
/* Module: uart_driver                                                        */
/* Description: Handles UART communication at 9600 baud                       */
/* ========================================================================== */

/**
 * @brief Initialize UART at 9600 baud
 */
void uart_driver_init(void)
{
    Serial.begin(9600);
}

/**
 * @brief Print "HELLO" message via UART
 * 
 * This function sends the string "HELLO" followed by a newline.
 * Called every 2 seconds from loop().
 */
void uart_driver_send_hello(void)
{
    Serial.println("HELLO");
}

/* ========================================================================== */
/* Main application                                                           */
/* ========================================================================== */

/**
 * @brief Timing variables for non-blocking 2-second interval
 * 
 * Using millis() to track elapsed time for the serial message,
 * while the LED blink uses delay() (blocking but acceptable for this simple app).
 */
static unsigned long last_hello_time = 0;
static const unsigned long hello_interval = 2000;  /* 2 seconds in milliseconds */

/**
 * @brief Arduino setup function
 * 
 * Initializes all modules and runs once at startup.
 */
void setup(void)
{
    /* Initialize modules */
    led_blink_init();
    uart_driver_init();
    
    /* Record initial time for serial message timing */
    last_hello_time = millis();
}

/**
 * @brief Arduino main loop
 * 
 * Runs continuously:
 * - Blinks LED with 200ms period (blocking delay)
 * - Sends "HELLO" every 2 seconds (non-blocking using millis())
 */
void loop(void)
{
    /* Update LED blink (200ms period) */
    led_blink_update();
    
    /* Check if 2 seconds have elapsed since last "HELLO" message */
    unsigned long current_time = millis();
    if (current_time - last_hello_time >= hello_interval)
    {
        uart_driver_send_hello();
        last_hello_time = current_time;
    }
}