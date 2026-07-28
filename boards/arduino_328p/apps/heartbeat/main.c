#include <avr/io.h>
#include <util/delay.h>

static uint16_t g_frame = 0;

static void uart_init(void) {
    UBRR0H = 0; UBRR0L = 103;
    UCSR0B = (1 << TXEN0);
    UCSR0C = (1 << UCSZ01) | (1 << UCSZ00);
}
static void uart_char(char c) {
    while (!(UCSR0A & (1 << UDRE0)));
    UDR0 = c;
}
static void uart_str(const char *s) {
    while (*s) uart_char(*s++);
}

int main(void) {
    uart_init();
    while (1) {
        g_frame++;
        uart_str("+-------- FRAME ");
        { char b[6]; int i=5; uint16_t n=g_frame; b[5]=0;
          while(n){b[--i]='0'+(n%10);n/=10;}
          if(i==5) b[--i]='0'; uart_str(&b[i]); }
        uart_str(" --------+\r\n");

        uart_str("    **       **    \r\n");
        uart_str("   ****     ****   \r\n");
        uart_str("  ******   ******  \r\n");
        uart_str(" ******** ******** \r\n");
        uart_str(" ***************   \r\n");
        uart_str("  *************    \r\n");
        uart_str("   ***********     \r\n");
        uart_str("    *********      \r\n");
        uart_str("     *******       \r\n");
        uart_str("      *****        \r\n");
        uart_str("       ***         \r\n");
        uart_str("        *          \r\n");
        uart_str("\r\n");

        _delay_ms(1000);
    }
    return 0;
}
