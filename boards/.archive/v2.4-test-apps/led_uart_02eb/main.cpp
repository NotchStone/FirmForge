#include <Arduino.h>
/* FirmForge Boot Signature — AVR UART0 (TX=pin1, 9600) */
namespace {
struct _FirmForgeBoot {
    _FirmForgeBoot() {
        UBRR0H = (unsigned char)(103 >> 8);
        UBRR0L = (unsigned char)(103);
        UCSR0B = (1 << TXEN0);
        UCSR0C = (3 << UCSZ00);
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=02eb44de\n";
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
 * Function 1: LED blink on pin 13 (LED_BUILTIN) with 200ms interval
 * Function 2: Serial print "HELLO" at 9600 baud every 1 second
 * 
 * F_CPU: 16 MHz
 * Flash: 256 KB
 * SRAM: 8 KB
 */

/* Pin definitions */
#define LED_PIN         13      /* Built-in LED on Arduino UNO R3 */
#define SERIAL_BAUD     9600    /* UART baud rate */

/* Timing constants (in milliseconds) */
#define LED_BLINK_INTERVAL_MS   200     /* LED on/off duration */
#define SERIAL_PRINT_INTERVAL_MS 1000   /* Serial message interval */

/* Function prototypes */
void led_blink_init(void);
void led_blink_toggle(void);
void uart_driver_init(void);
void uart_driver_print_hello(void);

/* Timing variables for non-blocking operation */
static unsigned long last_led_toggle_ms = 0;
static unsigned long last_serial_print_ms = 0;

/*
 * Initialize LED pin as output
 */
void led_blink_init(void)
{
    pinMode(LED_PIN, OUTPUT);
    digitalWrite(LED_PIN, LOW);     /* Start with LED off */
}

/*
 * Toggle the LED state
 */
void led_blink_toggle(void)
{
    static uint8_t led_state = LOW;
    
    led_state = (led_state == LOW) ? HIGH : LOW;
    digitalWrite(LED_PIN, led_state);
}

/*
 * Initialize UART communication at specified baud rate
 */
void uart_driver_init(void)
{
    Serial.begin(SERIAL_BAUD);
}

/*
 * Print "HELLO" message over UART
 */
void uart_driver_print_hello(void)
{
    Serial.println("HELLO");
}

/*
 * Arduino setup function - runs once at startup
 */
void setup(void)
{
    /* Initialize all modules */
    led_blink_init();
    uart_driver_init();
    
    /* Record initial time for timing reference */
    last_led_toggle_ms = millis();
    last_serial_print_ms = millis();
}

/*
 * Arduino loop function - runs repeatedly
 */
void loop(void)
{
    unsigned long current_time_ms = millis();
    
    /*
     * Task 1: LED blink with 200ms interval (non-blocking)
     * Toggle LED every LED_BLINK_INTERVAL_MS milliseconds
     */
    if ((current_time_ms - last_led_toggle_ms) >= LED_BLINK_INTERVAL_MS)
    {
        last_led_toggle_ms = current_time_ms;
        led_blink_toggle();
    }
    
    /*
     * Task 2: Serial print "HELLO" every 1 second (non-blocking)
     * Print message every SERIAL_PRINT_INTERVAL_MS milliseconds
     */
    if ((current_time_ms - last_serial_print_ms) >= SERIAL_PRINT_INTERVAL_MS)
    {
        last_serial_print_ms = current_time_ms;
        uart_driver_print_hello();
    }
}