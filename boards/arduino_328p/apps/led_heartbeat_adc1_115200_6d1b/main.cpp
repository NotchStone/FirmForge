#include <Arduino.h>
/* FirmForge Boot Signature — AVR UART0 (TX=pin1, 115200) */
namespace {
struct _FirmForgeBoot {
    _FirmForgeBoot() {
        UBRR0H = (unsigned char)(8 >> 8);
        UBRR0L = (unsigned char)(8);
        UCSR0B = (1 << TXEN0);
        UCSR0C = (3 << UCSZ00);
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=6d1b3f01\n";
        for (const char* p = sig; *p; p++) {
            while (!(UCSR0A & (1 << UDRE0))) { }
            UDR0 = (unsigned char)(*p);
        }
    }
} _firmforge_boot;
}

#define ADC_INPUT_PIN   A1
#define SERIAL_BAUD     115200UL
#define HEARTBEAT_MS    1000UL
#define LED_TOGGLE_MS   500UL
#define ADC_SAMPLES     4
#define VREF_MV         5000UL

static unsigned long g_seq          = 0;
static unsigned long g_last_hb      = 0;
static unsigned long g_last_led     = 0;
static bool          g_led_state    = false;

static uint16_t adc1_read(void) {
    uint32_t sum = 0;
    for (uint8_t i = 0; i < ADC_SAMPLES; i++) { sum += analogRead(ADC_INPUT_PIN); delay(1); }
    return (uint16_t)(sum / ADC_SAMPLES);
}
static uint16_t adc_to_mv(uint16_t raw) {
    return (uint16_t)((uint32_t)raw * VREF_MV / 1023UL);
}
static void send_heartbeat(uint16_t raw) {
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

void setup(void) {
    Serial.begin(SERIAL_BAUD);
    pinMode(LED_BUILTIN, OUTPUT); digitalWrite(LED_BUILTIN, LOW);
    pinMode(ADC_INPUT_PIN, INPUT);
    delay(100);
    Serial.println("FirmForge LED+Heartbeat+ADC1 @115200 started");
    g_last_hb = millis(); g_last_led = millis();
}

void loop(void) {
    unsigned long now = millis();
    if (now - g_last_led >= LED_TOGGLE_MS) {
        g_last_led = now; g_led_state = !g_led_state;
        digitalWrite(LED_BUILTIN, g_led_state ? HIGH : LOW);
    }
    if (now - g_last_hb >= HEARTBEAT_MS) {
        g_last_hb = now;
        send_heartbeat(adc1_read());
    }
}
