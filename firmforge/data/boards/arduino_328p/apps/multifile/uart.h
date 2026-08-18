#ifndef UART_H
#define UART_H
void uart_init(unsigned long baud);
void uart_putchar(char c);
void uart_print(const char *s);
#endif
