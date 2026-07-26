#include <Arduino.h>
/* FirmForge Boot Signature — AVR UART0 (TX=pin1, 9600) */
namespace {
struct _FirmForgeBoot {
    _FirmForgeBoot() {
        UBRR0H = (unsigned char)(103 >> 8);
        UBRR0L = (unsigned char)(103);
        UCSR0B = (1 << TXEN0);
        UCSR0C = (3 << UCSZ00);
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=82211d81\n";
        for (const char* p = sig; *p; p++) {
            while (!(UCSR0A & (1 << UDRE0))) { }
            UDR0 = (unsigned char)(*p);
        }
    }
} _firmforge_boot;
}

// LED SOS signal timing constants (in milliseconds)
#define SOS_DOT_DURATION_MS  200   // Duration of a short blink (dot)
#define SOS_DASH_DURATION_MS 600   // Duration of a long blink (dash)
#define SOS_SYMBOL_GAP_MS    200   // Gap between symbols within a letter
#define SOS_LETTER_GAP_MS    600   // Gap between letters (S, O, S)
#define SOS_CYCLE_GAP_MS     2000  // Gap between complete SOS cycles

// LED pin definition (built-in LED on Arduino UNO R3 is pin 13)
#define SOS_LED_PIN          LED_BUILTIN

/**
 * @brief  Blinks the LED for a specified duration (on then off).
 * @param  duration_ms  Time in milliseconds to keep the LED on.
 * @note   This is a blocking delay function.
 */
static void blink_led(uint16_t duration_ms) {
    digitalWrite(SOS_LED_PIN, HIGH);
    delay(duration_ms);
    digitalWrite(SOS_LED_PIN, LOW);
    delay(SOS_SYMBOL_GAP_MS);
}

/**
 * @brief  Sends an SOS pattern: 3 short, 3 long, 3 short blinks.
 * @note   Uses blocking delays; loop() calls this repeatedly.
 */
static void send_sos_signal(void) {
    // Three short blinks (S)
    for (uint8_t i = 0; i < 3; i++) {
        blink_led(SOS_DOT_DURATION_MS);
    }
    delay(SOS_LETTER_GAP_MS - SOS_SYMBOL_GAP_MS); // Adjust gap between letters

    // Three long blinks (O)
    for (uint8_t i = 0; i < 3; i++) {
        blink_led(SOS_DASH_DURATION_MS);
    }
    delay(SOS_LETTER_GAP_MS - SOS_SYMBOL_GAP_MS); // Adjust gap between letters

    // Three short blinks (S)
    for (uint8_t i = 0; i < 3; i++) {
        blink_led(SOS_DOT_DURATION_MS);
    }
}

/**
 * @brief  Arduino setup function. Initializes the LED pin and serial port.
 */
void setup(void) {
    // Initialize the built-in LED pin as an output
    pinMode(SOS_LED_PIN, OUTPUT);
    digitalWrite(SOS_LED_PIN, LOW); // Ensure LED starts off

    // Initialize serial communication for debugging (optional)
    Serial.begin(9600);
    Serial.println("SOS Signal Generator started.");
}

/**
 * @brief  Arduino main loop. Repeatedly sends the SOS signal.
 */
void loop(void) {
    send_sos_signal();
    delay(SOS_CYCLE_GAP_MS); // Wait before repeating the SOS pattern
}