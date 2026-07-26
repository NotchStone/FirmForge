#include <Arduino.h>
/* FirmForge Boot Signature — AVR UART0 (TX=pin1, 9600) */
namespace {
struct _FirmForgeBoot {
    _FirmForgeBoot() {
        UBRR0H = (unsigned char)(103 >> 8);
        UBRR0L = (unsigned char)(103);
        UCSR0B = (1 << TXEN0);
        UCSR0C = (3 << UCSZ00);
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=d6e98244\n";
        for (const char* p = sig; *p; p++) {
            while (!(UCSR0A & (1 << UDRE0))) { }
            UDR0 = (unsigned char)(*p);
        }
    }
} _firmforge_boot;
}

// UART configuration constants
#define SERIAL_BAUD_RATE 9600UL
#define COUNTER_INTERVAL_MS 1000UL

// Global counter variable
static unsigned long counter = 0;

// Function to initialize UART communication
void uart_init(void) {
    // Initialize serial communication at 9600 baud
    Serial.begin(SERIAL_BAUD_RATE);
    
    // Wait for serial port to initialize (optional, for USB serial)
    while (!Serial) {
        ; // Wait for serial connection (needed for some boards)
    }
    
    // Print startup message
    Serial.println("UART initialized at 9600 baud");
}

// Function to send counter value over UART
void uart_send_counter(unsigned long value) {
    Serial.print("Counter: ");
    Serial.println(value);
}

// Arduino setup function - runs once at startup
void setup(void) {
    // Initialize UART communication
    uart_init();
    
    // Print initial message
    Serial.println("Serial counter started (1 second interval)");
}

// Arduino main loop function - runs repeatedly
void loop(void) {
    // Increment counter
    counter++;
    
    // Send counter value over UART
    uart_send_counter(counter);
    
    // Wait for 1 second before next transmission
    delay(COUNTER_INTERVAL_MS);
}