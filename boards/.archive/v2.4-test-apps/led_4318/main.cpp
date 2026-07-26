#include <Arduino.h>
/* FirmForge Boot Signature — AVR UART0 (TX=pin1, 9600) */
namespace {
struct _FirmForgeBoot {
    _FirmForgeBoot() {
        UBRR0H = (unsigned char)(103 >> 8);
        UBRR0L = (unsigned char)(103);
        UCSR0B = (1 << TXEN0);
        UCSR0C = (3 << UCSZ00);
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=4318da07\n";
        for (const char* p = sig; *p; p++) {
            while (!(UCSR0A & (1 << UDRE0))) { }
            UDR0 = (unsigned char)(*p);
        }
    }
} _firmforge_boot;
}

/*
 * SOS Pattern Timing Constants (in milliseconds)
 * DOT:   200ms
 * DASH:  600ms
 * GAP:   200ms (between symbols)
 * CHAR:  600ms (between characters)
 * CYCLE: 2000ms (between SOS repetitions)
 */
#define SOS_DOT_DURATION_MS    200
#define SOS_DASH_DURATION_MS   600
#define SOS_SYMBOL_GAP_MS      200
#define SOS_CHAR_GAP_MS        600
#define SOS_CYCLE_GAP_MS       2000

/*
 * LED pin for SOS pattern
 * LED_BUILTIN is defined as 13 for Arduino UNO R3
 */
const uint8_t ledPin = LED_BUILTIN;

/*
 * Blink the LED for a given duration (on then off)
 * @param duration_ms: time in milliseconds to keep LED on
 */
void blinkSymbol(uint16_t duration_ms) {
    digitalWrite(ledPin, HIGH);
    delay(duration_ms);
    digitalWrite(ledPin, LOW);
    delay(SOS_SYMBOL_GAP_MS);
}

/*
 * Send the letter 'S' (three dots)
 */
void sendS(void) {
    for (uint8_t i = 0; i < 3; i++) {
        blinkSymbol(SOS_DOT_DURATION_MS);
    }
    delay(SOS_CHAR_GAP_MS - SOS_SYMBOL_GAP_MS);
}

/*
 * Send the letter 'O' (three dashes)
 */
void sendO(void) {
    for (uint8_t i = 0; i < 3; i++) {
        blinkSymbol(SOS_DASH_DURATION_MS);
    }
    delay(SOS_CHAR_GAP_MS - SOS_SYMBOL_GAP_MS);
}

/*
 * Play one full SOS pattern: ... --- ...
 */
void playSOS(void) {
    sendS();
    sendO();
    sendS();
    delay(SOS_CYCLE_GAP_MS);
}

void setup(void) {
    pinMode(ledPin, OUTPUT);
    digitalWrite(ledPin, LOW);
}

void loop(void) {
    playSOS();
}