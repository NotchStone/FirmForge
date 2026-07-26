#include <Arduino.h>
/* FirmForge Boot Signature — AVR UART0 (TX=pin1, 115200) */
namespace {
struct _FirmForgeBoot {
    _FirmForgeBoot() {
        UBRR0H = (unsigned char)(8 >> 8);
        UBRR0L = (unsigned char)(8);
        UCSR0B = (1 << TXEN0);
        UCSR0C = (3 << UCSZ00);
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=b0e4cb92\n";
        for (const char* p = sig; *p; p++) {
            while (!(UCSR0A & (1 << UDRE0))) { }
            UDR0 = (unsigned char)(*p);
        }
    }
} _firmforge_boot;
}

void setup(void)
{
    Serial.begin(115200);
    pinMode(LED_BUILTIN, OUTPUT);
    Serial.println("auto-baud test @115200 started");
}

void loop(void)
{
    digitalWrite(LED_BUILTIN, HIGH);
    delay(500);
    digitalWrite(LED_BUILTIN, LOW);
    delay(500);
    Serial.println("HEARTBEAT");
}
