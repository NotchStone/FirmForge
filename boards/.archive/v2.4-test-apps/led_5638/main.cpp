#include <Arduino.h>
/* FirmForge Boot Signature — AVR UART0 (TX=pin1, 9600) */
namespace {
struct _FirmForgeBoot {
    _FirmForgeBoot() {
        UBRR0H = (unsigned char)(103 >> 8);
        UBRR0L = (unsigned char)(103);
        UCSR0B = (1 << TXEN0);
        UCSR0C = (3 << UCSZ00);
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=56381639\n";
        for (const char* p = sig; *p; p++) {
            while (!(UCSR0A & (1 << UDRE0))) { }
            UDR0 = (unsigned char)(*p);
        }
    }
} _firmforge_boot;
}

/*
 * SOS Pattern Timing Constants (in milliseconds)
 * DOT:    200ms
 * DASH:   600ms
 * SYMBOL_GAP:   200ms (gap between dots/dashes within a letter)
 * LETTER_GAP:  600ms (gap between letters)
 * WORD_GAP:   1400ms (gap between SOS repetitions)
 */
#define SOS_DOT_MS         200
#define SOS_DASH_MS        600
#define SOS_SYMBOL_GAP_MS  200
#define SOS_LETTER_GAP_MS  600
#define SOS_WORD_GAP_MS   1400

/*
 * LED pin definition
 * LED_BUILTIN is defined as 13 for Arduino UNO R3
 */
const uint8_t ledPin = LED_BUILTIN;

/*
 * Function: ledOn
 * Turns the built-in LED on.
 */
void ledOn(void) {
    digitalWrite(ledPin, HIGH);
}

/*
 * Function: ledOff
 * Turns the built-in LED off.
 */
void ledOff(void) {
    digitalWrite(ledPin, LOW);
}

/*
 * Function: blinkDot
 * Blinks the LED for a short duration (dot).
 */
void blinkDot(void) {
    ledOn();
    delay(SOS_DOT_MS);
    ledOff();
    delay(SOS_SYMBOL_GAP_MS);
}

/*
 * Function: blinkDash
 * Blinks the LED for a long duration (dash).
 */
void blinkDash(void) {
    ledOn();
    delay(SOS_DASH_MS);
    ledOff();
    delay(SOS_SYMBOL_GAP_MS);
}

/*
 * Function: sendSOSLetterS
 * Sends the letter 'S' in Morse code: three dots.
 */
void sendSOSLetterS(void) {
    blinkDot();
    blinkDot();
    blinkDot();
    delay(SOS_LETTER_GAP_MS - SOS_SYMBOL_GAP_MS); // adjust for last symbol gap
}

/*
 * Function: sendSOSLetterO
 * Sends the letter 'O' in Morse code: three dashes.
 */
void sendSOSLetterO(void) {
    blinkDash();
    blinkDash();
    blinkDash();
    delay(SOS_LETTER_GAP_MS - SOS_SYMBOL_GAP_MS); // adjust for last symbol gap
}

/*
 * Function: sendSOSPattern
 * Sends one complete SOS pattern: ... --- ...
 * Followed by a word gap before the next repetition.
 */
void sendSOSPattern(void) {
    sendSOSLetterS();
    sendSOSLetterO();
    sendSOSLetterS();
    delay(SOS_WORD_GAP_MS - SOS_LETTER_GAP_MS); // adjust for last letter gap
}

/*
 * setup()
 * Initializes the LED pin as output.
 * Called once at startup by the Arduino framework.
 */
void setup(void) {
    pinMode(ledPin, OUTPUT);
    digitalWrite(ledPin, LOW); // ensure LED starts off
}

/*
 * loop()
 * Repeatedly sends the SOS pattern.
 * Called continuously by the Arduino framework.
 */
void loop(void) {
    sendSOSPattern();
}