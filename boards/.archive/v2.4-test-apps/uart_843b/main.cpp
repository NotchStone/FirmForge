#include <Arduino.h>
/* FirmForge Boot Signature — AVR UART0 (TX=pin1, 9600) */
namespace {
struct _FirmForgeBoot {
    _FirmForgeBoot() {
        UBRR0H = (unsigned char)(103 >> 8);
        UBRR0L = (unsigned char)(103);
        UCSR0B = (1 << TXEN0);
        UCSR0C = (3 << UCSZ00);
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=843b417d\n";
        for (const char* p = sig; *p; p++) {
            while (!(UCSR0A & (1 << UDRE0))) { }
            UDR0 = (unsigned char)(*p);
        }
    }
} _firmforge_boot;
}

/*
 * ASCII Table Printer
 * 
 * Prints the full ASCII table (characters 32-126) via serial,
 * one character per line, every 10 seconds.
 * 
 * Hardware: Arduino UNO R3 (ATmega328P)
 * Serial: 9600 baud, 8N1
 */

/* Constants */
#define SERIAL_BAUD_RATE      9600UL
#define ASCII_START           32
#define ASCII_END             126
#define PRINT_INTERVAL_MS     10000UL

/* Module: uart_driver */
/* Handles serial communication for ASCII table printing */

/* Global variables */
static unsigned long lastPrintTime = 0;
static uint8_t currentChar = ASCII_START;

/* Function prototypes */
void printAsciiTable(void);

/**
 * @brief Prints one ASCII character with its decimal value
 * 
 * Output format: "Decimal: <value> | Char: <character>"
 */
void printAsciiTable(void)
{
    /* Print decimal value */
    Serial.print("Decimal: ");
    Serial.print(currentChar);
    Serial.print(" | Char: ");
    
    /* Print the character itself */
    Serial.write(currentChar);
    Serial.println();
    
    /* Move to next character */
    currentChar++;
    
    /* Reset to start if we've printed all characters */
    if (currentChar > ASCII_END) {
        currentChar = ASCII_START;
    }
}

/**
 * @brief Arduino setup function
 * 
 * Initializes serial communication at 9600 baud.
 * Called once at startup.
 */
void setup(void)
{
    /* Initialize serial communication */
    Serial.begin(SERIAL_BAUD_RATE);
    
    /* Wait for serial port to connect (important for some boards) */
    while (!Serial) {
        ; /* Wait for serial connection */
    }
    
    /* Print header message */
    Serial.println("ASCII Table Printer");
    Serial.println("Printing one character every 10 seconds");
    Serial.println("----------------------------------------");
    
    /* Initialize timing */
    lastPrintTime = millis();
}

/**
 * @brief Arduino main loop function
 * 
 * Prints one ASCII character every 10 seconds.
 * Uses non-blocking timing with millis().
 */
void loop(void)
{
    unsigned long currentTime = millis();
    
    /* Check if 10 seconds have elapsed */
    if (currentTime - lastPrintTime >= PRINT_INTERVAL_MS) {
        lastPrintTime = currentTime;
        printAsciiTable();
    }
}