#include <Arduino.h>
/* FirmForge Boot Signature — AVR UART0 (TX=pin1, 9600) */
namespace {
struct _FirmForgeBoot {
    _FirmForgeBoot() {
        UBRR0H = (unsigned char)(103 >> 8);
        UBRR0L = (unsigned char)(103);
        UCSR0B = (1 << TXEN0);
        UCSR0C = (3 << UCSZ00);
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=3ee7dca0\n";
        for (const char* p = sig; *p; p++) {
            while (!(UCSR0A & (1 << UDRE0))) { }
            UDR0 = (unsigned char)(*p);
        }
    }
} _firmforge_boot;
}

/* ============================================================
 *  Constants and Definitions
 * ============================================================ */
#define ADC_INPUT_PIN       A0          /* Analog input for base period */
#define LED_PIN             LED_BUILTIN /* Built-in LED on pin 13 */
#define SERIAL_BAUD         9600        /* UART baud rate */
#define ADC_REF_VOLTAGE     5.0         /* Reference voltage in volts */
#define ADC_RESOLUTION      1023        /* 10-bit ADC max value */

/* Blink pattern multipliers */
#define FIRST_CYCLE_MULTIPLIER  1
#define SECOND_CYCLE_MULTIPLIER 3

/* ============================================================
 *  Module: adc_driver
 *  Description: Reads analog voltage from specified pin and
 *               returns the value in milliseconds (0-1023 ms).
 * ============================================================ */
static uint16_t adc_read_period_ms(void)
{
    uint16_t raw_value = analogRead(ADC_INPUT_PIN);
    /* Map ADC value (0-1023) directly to milliseconds (0-1023 ms) */
    return raw_value;
}

/* ============================================================
 *  Module: led_blink
 *  Description: Controls the built-in LED with a given on/off
 *               duration in milliseconds.
 * ============================================================ */
static void led_blink(uint16_t period_ms)
{
    /* Turn LED on */
    digitalWrite(LED_PIN, HIGH);
    delay(period_ms);

    /* Turn LED off */
    digitalWrite(LED_PIN, LOW);
    delay(period_ms);
}

/* ============================================================
 *  Module: uart_driver
 *  Description: Sends a formatted heartbeat message over UART.
 * ============================================================ */
static void uart_send_heartbeat(uint16_t cycle_number, uint16_t adc_value_ms)
{
    Serial.print("HEART #");
    Serial.print(cycle_number);
    Serial.print(": ADC=");
    Serial.print(adc_value_ms);
    Serial.println("ms");
}

/* ============================================================
 *  Arduino Setup
 *  Initializes serial communication and configures GPIO pins.
 * ============================================================ */
void setup(void)
{
    /* Initialize UART at 9600 baud */
    Serial.begin(SERIAL_BAUD);

    /* Configure LED pin as output */
    pinMode(LED_PIN, OUTPUT);

    /* Ensure LED starts off */
    digitalWrite(LED_PIN, LOW);

    /* Small delay to allow serial monitor to connect */
    delay(100);
}

/* ============================================================
 *  Arduino Main Loop
 *  Reads ADC, blinks LED with pattern, and sends serial message.
 *  Pattern: first cycle = period ms, second cycle = 3x period ms.
 * ============================================================ */
void loop(void)
{
    static uint16_t cycle_counter = 0;
    uint16_t base_period_ms;
    uint16_t blink_period_ms;

    /* Read base period from ADC (0-1023 ms) */
    base_period_ms = adc_read_period_ms();

    /* Determine blink period based on cycle number */
    if ((cycle_counter % 2) == 0)
    {
        /* Even cycle: first cycle multiplier */
        blink_period_ms = base_period_ms * FIRST_CYCLE_MULTIPLIER;
    }
    else
    {
        /* Odd cycle: second cycle multiplier */
        blink_period_ms = base_period_ms * SECOND_CYCLE_MULTIPLIER;
    }

    /* Perform LED blink with calculated period */
    led_blink(blink_period_ms);

    /* Send heartbeat message over UART */
    uart_send_heartbeat(cycle_counter + 1, base_period_ms);

    /* Increment cycle counter */
    cycle_counter++;
}