#include <Arduino.h>
/* FirmForge Boot Signature — AVR UART0 (TX=pin1, 9600) */
namespace {
struct _FirmForgeBoot {
    _FirmForgeBoot() {
        UBRR0H = (unsigned char)(103 >> 8);
        UBRR0L = (unsigned char)(103);
        UCSR0B = (1 << TXEN0);
        UCSR0C = (3 << UCSZ00);
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=270d0023\n";
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
#define ADC_INPUT_PIN          A0
#define LED_PIN                LED_BUILTIN   /* Pin 13 */
#define SERIAL_BAUD            9600UL
#define ADC_SAMPLE_COUNT       4             /* Number of samples for averaging */

/* ============================================================
 *  Module: adc_driver
 *  Reads analog pin A0 and returns averaged value in ms.
 * ============================================================ */
static uint16_t adc_read_period_ms(void)
{
    uint32_t sum = 0;

    /* Take multiple samples and average to reduce noise */
    for (uint8_t i = 0; i < ADC_SAMPLE_COUNT; i++) {
        sum += analogRead(ADC_INPUT_PIN);
        delay(1);   /* Small delay between samples for settling */
    }

    /* Convert average ADC value (0-1023) to milliseconds (range 0-1023 ms) */
    uint16_t avg = (uint16_t)(sum / ADC_SAMPLE_COUNT);
    return avg;
}

/* ============================================================
 *  Module: led_blink
 *  Controls the built-in LED with specified on/off timing.
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
 *  Sends formatted heartbeat message over UART.
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
 * ============================================================ */
void setup(void)
{
    /* Initialize serial communication */
    Serial.begin(SERIAL_BAUD);

    /* Configure LED pin as output */
    pinMode(LED_PIN, OUTPUT);
    digitalWrite(LED_PIN, LOW);   /* Ensure LED starts off */

    /* Configure ADC pin as input (default, but explicit for clarity) */
    pinMode(ADC_INPUT_PIN, INPUT);

    /* Small delay for system stabilization */
    delay(100);
}

/* ============================================================
 *  Arduino Main Loop
 *  Blink pattern: first cycle = period ms, second cycle = 3x period ms
 *  Each blink sends serial heartbeat message.
 * ============================================================ */
void loop(void)
{
    static uint16_t cycle_counter = 0;

    /* Read base period from ADC */
    uint16_t base_period_ms = adc_read_period_ms();

    /* Determine blink period based on cycle number (0-based) */
    uint16_t blink_period_ms;
    if ((cycle_counter % 2) == 0) {
        /* Even cycles: first blink = base period */
        blink_period_ms = base_period_ms;
    } else {
        /* Odd cycles: second blink = 3x base period */
        blink_period_ms = (uint16_t)((uint32_t)base_period_ms * 3UL);
    }

    /* Perform LED blink */
    led_blink(blink_period_ms);

    /* Send heartbeat message over UART */
    uart_send_heartbeat(cycle_counter, base_period_ms);

    /* Increment cycle counter */
    cycle_counter++;
}