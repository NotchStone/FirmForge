#include <Arduino.h>
/* FirmForge Boot Signature — AVR UART0 (TX=pin1, 9600) */
namespace {
struct _FirmForgeBoot {
    _FirmForgeBoot() {
        UBRR0H = (unsigned char)(103 >> 8);
        UBRR0L = (unsigned char)(103);
        UCSR0B = (1 << TXEN0);
        UCSR0C = (3 << UCSZ00);
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=1e1e4aea\n";
        for (const char* p = sig; *p; p++) {
            while (!(UCSR0A & (1 << UDRE0))) { }
            UDR0 = (unsigned char)(*p);
        }
    }
} _firmforge_boot;
}

/*
 * main.c - LED blink and UART communication for Arduino UNO R3 (ATmega328P)
 * 
 * Function 1: LED_BUILTIN (pin 13) blinks with 200ms period
 * Function 2: Serial prints "HELLO" at 9600 baud every 1 second
 * 
 * F_CPU: 16 MHz
 * Flash: 256 KB
 * SRAM: 8 KB
 */

// Pin definitions
#define LED_PIN         13      // LED_BUILTIN on Arduino UNO R3
#define SERIAL_BAUD     9600    // UART baud rate

// Timing constants (in milliseconds)
#define BLINK_INTERVAL  200     // LED toggle interval
#define PRINT_INTERVAL  1000    // Serial print interval

// Function prototypes
void led_blink_init(void);
void led_blink_update(void);
void uart_driver_init(void);
void uart_driver_update(void);

// Timing variables for non-blocking operation
static unsigned long last_blink_time = 0;
static unsigned long last_print_time = 0;
static uint8_t led_state = LOW;

void setup(void)
{
    // Initialize LED pin
    led_blink_init();
    
    // Initialize UART communication
    uart_driver_init();
    
    // Initialize timing variables
    last_blink_time = millis();
    last_print_time = millis();
}

void loop(void)
{
    // Update LED blink state (non-blocking)
    led_blink_update();
    
    // Update serial print (non-blocking)
    uart_driver_update();
}

/*
 * LED Blink Module
 * Toggles LED_BUILTIN at BLINK_INTERVAL ms
 */
void led_blink_init(void)
{
    // Configure LED pin as output
    pinMode(LED_PIN, OUTPUT);
    
    // Initialize LED to OFF state
    digitalWrite(LED_PIN, LOW);
}

void led_blink_update(void)
{
    unsigned long current_time = millis();
    
    // Check if it's time to toggle the LED
    if ((current_time - last_blink_time) >= BLINK_INTERVAL)
    {
        // Update last blink timestamp
        last_blink_time = current_time;
        
        // Toggle LED state
        led_state = (led_state == HIGH) ? LOW : HIGH;
        digitalWrite(LED_PIN, led_state);
    }
}

/*
 * UART Driver Module
 * Prints "HELLO" every PRINT_INTERVAL ms at SERIAL_BAUD baud
 */
void uart_driver_init(void)
{
    // Initialize serial communication at specified baud rate
    Serial.begin(SERIAL_BAUD);
    
    // Wait for serial port to connect (optional, for USB serial)
    // On Arduino UNO, this is not strictly necessary but good practice
    delay(100);
}

void uart_driver_update(void)
{
    unsigned long current_time = millis();
    
    // Check if it's time to print the message
    if ((current_time - last_print_time) >= PRINT_INTERVAL)
    {
        // Update last print timestamp
        last_print_time = current_time;
        
        // Print HELLO message via serial
        Serial.println("HELLO");
    }
}