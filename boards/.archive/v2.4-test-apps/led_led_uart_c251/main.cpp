/*
 * main.c - LED Blink with Heartbeat and Serial Counter
 * 
 * Hardware: Arduino UNO R3 (ATmega328P, 16MHz)
 * 
 * Functionality:
 * - LED_BUILTIN (pin 13) blinks in alternating cycle: 1s on, 1s off; 3s on, 3s off; 5s on, 5s off
 * - Each blink prints a heartbeat counter over UART at 9600 baud
 * - Non-blocking timing using millis()
 * 
 * Modules:
 *   led_blink.c     - LED blinking control
 *   led_heartbeat.c - Heartbeat counter management
 *   uart_driver.c   - UART communication
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
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=c2513013\n";
        for (const char* p = sig; *p; p++) {
            while (!(UCSR0A & (1 << UDRE0))) { }
            UDR0 = (unsigned char)(*p);
        }
    }
} _firmforge_boot;
}

/* ========================================================================== */
/* Module: led_blink.c                                                        */
/* ========================================================================== */

/*
 * LED blink timing constants (in milliseconds)
 * Cycle: 1s, 3s, 5s alternating
 */
#define BLINK_INTERVAL_1S  1000UL
#define BLINK_INTERVAL_3S  3000UL
#define BLINK_INTERVAL_5S  5000UL

/* Number of blink intervals in the cycle */
#define BLINK_CYCLE_COUNT  3

/* LED state */
static uint8_t  led_state = LOW;
static uint8_t  blink_phase = 0;  /* 0: 1s, 1: 3s, 2: 5s */
static unsigned long last_blink_time = 0;

/* Array of blink intervals for the cycle */
static const unsigned long blink_intervals[BLINK_CYCLE_COUNT] = {
    BLINK_INTERVAL_1S,
    BLINK_INTERVAL_3S,
    BLINK_INTERVAL_5S
};

/*
 * Initialize LED pin
 */
void led_blink_init(void)
{
    pinMode(LED_BUILTIN, OUTPUT);
    digitalWrite(LED_BUILTIN, LOW);
    led_state = LOW;
    blink_phase = 0;
    last_blink_time = 0;
}

/*
 * Update LED blink state (non-blocking)
 * Returns: 1 if LED state changed, 0 otherwise
 */
uint8_t led_blink_update(void)
{
    unsigned long current_time = millis();
    unsigned long interval = blink_intervals[blink_phase];
    
    if ((current_time - last_blink_time) >= interval)
    {
        /* Toggle LED */
        led_state = !led_state;
        digitalWrite(LED_BUILTIN, led_state);
        
        /* Update timing */
        last_blink_time = current_time;
        
        /* Advance to next phase when LED turns off (falling edge) */
        if (led_state == LOW)
        {
            blink_phase = (blink_phase + 1) % BLINK_CYCLE_COUNT;
        }
        
        return 1;  /* State changed */
    }
    
    return 0;  /* No change */
}

/*
 * Get current LED state
 */
uint8_t led_blink_get_state(void)
{
    return led_state;
}

/*
 * Get current blink phase index (0=1s, 1=3s, 2=5s)
 */
uint8_t led_blink_get_phase(void)
{
    return blink_phase;
}

/* ========================================================================== */
/* Module: led_heartbeat.c                                                    */
/* ========================================================================== */

/* Heartbeat counter */
static unsigned long heartbeat_counter = 0;

/*
 * Initialize heartbeat counter
 */
void led_heartbeat_init(void)
{
    heartbeat_counter = 0;
}

/*
 * Increment heartbeat counter
 * Called each time LED state changes (blink event)
 */
void led_heartbeat_tick(void)
{
    heartbeat_counter++;
}

/*
 * Get current heartbeat count
 */
unsigned long led_heartbeat_get_count(void)
{
    return heartbeat_counter;
}

/* ========================================================================== */
/* Module: uart_driver.c                                                      */
/* ========================================================================== */

/*
 * UART baud rate
 */
#define UART_BAUD_RATE  9600UL

/*
 * Initialize UART communication
 */
void uart_driver_init(void)
{
    Serial.begin(UART_BAUD_RATE);
    
    /* Wait for serial port to stabilize (optional, for USB-serial adapters) */
    while (!Serial)
    {
        ;  /* Wait for serial connection (needed for some boards) */
    }
}

/*
 * Print heartbeat message over UART
 * Format: "Heartbeat: <count>, Phase: <phase>, LED: <ON/OFF>\n"
 */
void uart_driver_print_heartbeat(unsigned long count, uint8_t phase, uint8_t led_state)
{
    Serial.print("Heartbeat: ");
    Serial.print(count);
    Serial.print(", Phase: ");
    Serial.print(phase);
    Serial.print("s, LED: ");
    if (led_state == HIGH)
    {
        Serial.print("ON");
    }
    else
    {
        Serial.print("OFF");
    }
    Serial.println();
}

/* ========================================================================== */
/* Main Application                                                           */
/* ========================================================================== */

/*
 * Setup function - called once at startup
 */
void setup(void)
{
    /* Initialize all modules */
    uart_driver_init();
    led_blink_init();
    led_heartbeat_init();
    
    /* Print startup message */
    Serial.println("LED Blink Heartbeat System Started");
    Serial.print("Blink cycle: 1s, 3s, 5s alternating");
    Serial.println();
}

/*
 * Main loop - runs continuously
 */
void loop(void)
{
    /* Update LED blink state */
    if (led_blink_update())
    {
        /* LED state changed - update heartbeat and print */
        led_heartbeat_tick();
        
        unsigned long count = led_heartbeat_get_count();
        uint8_t phase = led_blink_get_phase();
        uint8_t state = led_blink_get_state();
        
        uart_driver_print_heartbeat(count, phase, state);
    }
    
    /* Small delay to prevent tight loop (optional, improves stability) */
    delay(10);
}