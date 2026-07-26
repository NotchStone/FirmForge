/*
 * main.c - LED blink with heartbeat and serial counter
 * Target: Arduino UNO R3 (ATmega328P, 16MHz)
 * Features:
 *   1. LED blink with alternating cycle: 1s, 3s, 5s
 *   2. LED heartbeat (brief flash on each blink)
 *   3. UART serial counter output at 9600 baud
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
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=632a9d13\n";
        for (const char* p = sig; *p; p++) {
            while (!(UCSR0A & (1 << UDRE0))) { }
            UDR0 = (unsigned char)(*p);
        }
    }
} _firmforge_boot;
}

/* ==========================================================================
 * Module: led_blink
 * Description: Controls LED blinking with alternating on/off intervals
 * ========================================================================== */

/* Blink timing constants (in milliseconds) */
#define BLINK_INTERVAL_1   1000UL   /* 1 second */
#define BLINK_INTERVAL_2   3000UL   /* 3 seconds */
#define BLINK_INTERVAL_3   5000UL   /* 5 seconds */

/* Number of intervals in the alternating cycle */
#define BLINK_CYCLE_COUNT  3

/* Blink state structure */
typedef struct {
    uint8_t  cycle_index;           /* Current position in cycle (0,1,2) */
    uint8_t  led_state;             /* Current LED state (HIGH/LOW) */
    unsigned long last_toggle;      /* Timestamp of last toggle */
    unsigned long current_interval; /* Current active interval */
} BlinkState;

static BlinkState blink = {0, LOW, 0, BLINK_INTERVAL_1};

/* Initialize LED pin */
void led_blink_init(void) {
    pinMode(LED_BUILTIN, OUTPUT);
    digitalWrite(LED_BUILTIN, LOW);
    blink.last_toggle = millis();
}

/* Update blink state - call in loop() */
void led_blink_update(void) {
    unsigned long now = millis();
    
    /* Check if it's time to toggle */
    if ((now - blink.last_toggle) >= blink.current_interval) {
        /* Toggle LED */
        blink.led_state = !blink.led_state;
        digitalWrite(LED_BUILTIN, blink.led_state);
        blink.last_toggle = now;
        
        /* Advance to next interval in cycle */
        blink.cycle_index = (blink.cycle_index + 1) % BLINK_CYCLE_COUNT;
        switch (blink.cycle_index) {
            case 0:
                blink.current_interval = BLINK_INTERVAL_1;
                break;
            case 1:
                blink.current_interval = BLINK_INTERVAL_2;
                break;
            case 2:
                blink.current_interval = BLINK_INTERVAL_3;
                break;
        }
    }
}

/* ==========================================================================
 * Module: led_heartbeat
 * Description: Brief flash (heartbeat) on each LED toggle
 * ========================================================================== */

/* Heartbeat flash duration (milliseconds) */
#define HEARTBEAT_DURATION  50UL

/* Heartbeat state structure */
typedef struct {
    uint8_t  active;                /* Non-zero if heartbeat flash is active */
    unsigned long start_time;       /* When heartbeat started */
} HeartbeatState;

static HeartbeatState heartbeat = {0, 0};

/* Initialize heartbeat */
void led_heartbeat_init(void) {
    /* No special init needed - uses same LED pin */
}

/* Trigger a heartbeat flash */
void led_heartbeat_trigger(void) {
    heartbeat.active = 1;
    heartbeat.start_time = millis();
    digitalWrite(LED_BUILTIN, HIGH);  /* Turn LED on for flash */
}

/* Update heartbeat - call in loop() */
void led_heartbeat_update(void) {
    if (heartbeat.active) {
        unsigned long now = millis();
        if ((now - heartbeat.start_time) >= HEARTBEAT_DURATION) {
            /* End heartbeat flash - restore blink state */
            digitalWrite(LED_BUILTIN, blink.led_state);
            heartbeat.active = 0;
        }
    }
}

/* ==========================================================================
 * Module: uart_driver
 * Description: Serial communication at 9600 baud with counter output
 * ========================================================================== */

/* Serial baud rate */
#define SERIAL_BAUD         9600UL

/* Counter output interval (milliseconds) */
#define COUNTER_INTERVAL    1000UL

/* UART state structure */
typedef struct {
    unsigned long counter;          /* Heartbeat counter value */
    unsigned long last_output;      /* Timestamp of last counter output */
} UartState;

static UartState uart = {0, 0};

/* Initialize UART */
void uart_driver_init(void) {
    Serial.begin(SERIAL_BAUD);
    uart.last_output = millis();
}

/* Update UART - call in loop() */
void uart_driver_update(void) {
    unsigned long now = millis();
    
    /* Output counter every second */
    if ((now - uart.last_output) >= COUNTER_INTERVAL) {
        uart.counter++;
        Serial.print("Heartbeat counter: ");
        Serial.println(uart.counter);
        uart.last_output = now;
    }
}

/* ==========================================================================
 * Main Arduino entry points
 * ========================================================================== */

void setup(void) {
    /* Initialize all modules */
    led_blink_init();
    led_heartbeat_init();
    uart_driver_init();
}

void loop(void) {
    /* Update blink state */
    led_blink_update();
    
    /* If LED just turned on, trigger heartbeat flash */
    if (blink.led_state == HIGH) {
        /* Check if we just toggled on (within last 10ms) */
        static uint8_t last_led_state = LOW;
        if (last_led_state == LOW && blink.led_state == HIGH) {
            led_heartbeat_trigger();
        }
        last_led_state = blink.led_state;
    }
    
    /* Update heartbeat (may override LED state briefly) */
    led_heartbeat_update();
    
    /* Update serial output */
    uart_driver_update();
}