#include <Arduino.h>
/* FirmForge Boot Signature — AVR UART0 (TX=pin1, 115200) */
namespace {
struct _FirmForgeBoot {
    _FirmForgeBoot() {
        UBRR0H = (unsigned char)(8 >> 8);
        UBRR0L = (unsigned char)(8);
        UCSR0B = (1 << TXEN0);
        UCSR0C = (3 << UCSZ00);
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=4c8a7772\n";
        for (const char* p = sig; *p; p++) {
            while (!(UCSR0A & (1 << UDRE0))) { }
            UDR0 = (unsigned char)(*p);
        }
    }
} _firmforge_boot;
}

/* ============================================================
 *  Serial Heartbeat @115200 + ADC Channel 1 Monitor
 *  - Sends a heartbeat packet once per second
 *  - Reports the current value of ADC channel 1 (A1 / PC1)
 *  - Baud rate: 115200 bps
 *  - Non-blocking loop (millis-based timing)
 * ============================================================ */

#define ADC_INPUT_PIN   A1          /* ADC channel 1 -> pin A1 (PC1) */
#define SERIAL_BAUD     115200UL
#define HEARTBEAT_MS    1000UL      /* 1 second interval */
#define ADC_AVG_SAMPLES 4           /* moving-average samples to reduce noise */
#define VREF_MV         5000UL      /* AVR VCC reference ~5.0V */

static unsigned long g_seq = 0;
static unsigned long g_last_heartbeat = 0;

/* Read ADC channel 1 and return averaged raw value (0..1023) */
static uint16_t adc1_read_avg(void)
{
    uint32_t sum = 0;
    for (uint8_t i = 0; i < ADC_AVG_SAMPLES; i++) {
        sum += analogRead(ADC_INPUT_PIN);
        delay(1);
    }
    return (uint16_t)(sum / ADC_AVG_SAMPLES);
}

/* Convert raw ADC value (0..1023) to millivolts (0..5000) */
static uint16_t adc_to_mv(uint16_t raw)
{
    return (uint16_t)((uint32_t)raw * VREF_MV / 1023UL);
}

/* Build and send one heartbeat packet */
static void send_heartbeat(uint16_t raw)
{
    uint16_t mv = adc_to_mv(raw);
    Serial.print("HEARTBEAT #");
    Serial.print(g_seq);
    Serial.print(" adc1=");
    Serial.print(raw);
    Serial.print(" (");
    Serial.print(mv);
    Serial.println(" mV)");
    g_seq++;
}

void setup(void)
{
    Serial.begin(SERIAL_BAUD);
    pinMode(ADC_INPUT_PIN, INPUT);
    delay(100);
    Serial.println("FirmForge Heartbeat+ADC1 monitor @115200 started");
    g_last_heartbeat = millis();
}

void loop(void)
{
    unsigned long now = millis();
    if (now - g_last_heartbeat >= HEARTBEAT_MS) {
        g_last_heartbeat = now;
        uint16_t raw = adc1_read_avg();
        send_heartbeat(raw);
    }
}
