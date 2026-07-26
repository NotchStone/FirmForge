// R05: Serial echo — received char sent back, CR → newline
#include <avr/io.h>

#define BAUD 9600
#define UBRR_VAL ((F_CPU / 16 / BAUD) - 1)
void uart_init(){UBRR0H=UBRR_VAL>>8;UBRR0L=UBRR_VAL;UCSR0B=(1<<RXEN0)|(1<<TXEN0);UCSR0C=(1<<UCSZ01)|(1<<UCSZ00);}
void uart_tx(char c){while(!(UCSR0A&(1<<UDRE0)));UDR0=c;}
char uart_rx(){while(!(UCSR0A&(1<<RXC0)));return UDR0;}

int main(void) {
    uart_init();
    uart_tx('>');
    while (1) {
        char c = uart_rx();
        uart_tx(c);
        if (c == '\r') uart_tx('\n');
    }
}
