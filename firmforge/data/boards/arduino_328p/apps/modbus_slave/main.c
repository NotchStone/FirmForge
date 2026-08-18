/*
 * Modbus RTU Slave - ATmega328P (Arduino UNO)
 * ------------------------------------------------------------------
 * Function codes:
 *   03  Read Holding Registers   (0x0000-0x001F, 32 regs)
 *   04  Read Input Registers     (0x0000-0x0007, 8  regs, dynamic)
 *   06  Write Single Register    (holding)
 *   16  Write Multiple Registers (holding, 0x10)
 * Slave address: 1, UART0 9600 8N1
 * ------------------------------------------------------------------
 * Holding regs:  reg[0]=0x1234 marker, reg[i]=1000+i (i>0)
 * Input regs:    [0-3]=ADC0-3, [4]=uptime ms L16, [5]=frame count,
 *                [6]=0xCAFE marker, [7]=0
 */
#include <avr/io.h>
#include <avr/interrupt.h>
#include <stdint.h>

#define SLAVE_ADDR       1
#define MB_HOLDING_REGS  32
#define MB_INPUT_REGS    8
#define MB_BUF_SZ        64
#define FRAME_TIMEOUT_MS 5

#define LED_DDR   DDRB
#define LED_PORT  PORTB
#define LED_PIN   PB5

static uint16_t g_holding[MB_HOLDING_REGS];
static uint16_t g_inputs[MB_INPUT_REGS];
static volatile uint32_t g_tick_ms = 0;
static volatile uint32_t g_last_rx_ms = 0;
static volatile uint8_t g_rx_buf[MB_BUF_SZ];
static volatile uint8_t g_rx_head = 0;
static volatile uint8_t g_rx_tail = 0;
static uint16_t g_frame_count = 0;

/* ------------------------- UART0 ------------------------- */
static void uart_init(void) {
    UBRR0H = 0;
    UBRR0L = 103;                       /* 9600 baud @ 16MHz */
    UCSR0B = (1 << RXEN0) | (1 << TXEN0) | (1 << RXCIE0);
    UCSR0C = (1 << UCSZ01) | (1 << UCSZ00);  /* 8N1 */
}

static void uart_putc(char c) {
    while (!(UCSR0A & (1 << UDRE0))) ;
    UDR0 = c;
}

static void uart_puts(const char *s) {
    while (*s) uart_putc(*s++);
}

static void uart_puthex8(uint8_t v) {
    static const char h[] = "0123456789ABCDEF";
    uart_putc(h[(v >> 4) & 0xF]);
    uart_putc(h[v & 0xF]);
}

static void uart_puthex16(uint16_t v) {
    uart_puthex8((uint8_t)(v >> 8));
    uart_puthex8((uint8_t)v);
}

static void uart_putdec16(uint16_t v) {
    char buf[6];
    uint8_t i = 0;
    if (!v) { uart_putc('0'); return; }
    while (v) { buf[i++] = '0' + (v % 10); v /= 10; }
    while (i) uart_putc(buf[--i]);
}

/* ------------------- Timer0: 1ms tick ------------------- */
static void timer_init(void) {
    TCCR0A = (1 << WGM01);             /* CTC mode */
    TCCR0B = (1 << CS01) | (1 << CS00);/* prescaler /64 */
    OCR0A  = 249;                      /* 1ms @ 16MHz */
    TIMSK0 = (1 << OCIE0A);
}

ISR(TIMER0_COMPA_vect) {
    g_tick_ms++;
}

/* ----------------------- UART RX ------------------------ */
ISR(USART_RX_vect) {
    uint8_t b = UDR0;
    uint8_t next = (g_rx_head + 1) % MB_BUF_SZ;
    if (next != g_rx_tail) {
        g_rx_buf[g_rx_head] = b;
        g_rx_head = next;
    }
    g_last_rx_ms = g_tick_ms;
}

/* ------------------------- ADC -------------------------- */
static uint16_t adc_read(uint8_t ch) {
    ADMUX  = (1 << REFS0) | (ch & 0x07);          /* AVCC, channel */
    ADCSRA = (1 << ADEN) | (1 << ADSC) |          /* enable + start */
             (1 << ADPS2) | (1 << ADPS1) | (1 << ADPS0); /* /128 */
    while (ADCSRA & (1 << ADSC)) ;
    return ADC;
}

/* -------------------- Modbus CRC-16 --------------------- */
static uint16_t modbus_crc(const uint8_t *d, uint8_t len) {
    uint16_t crc = 0xFFFF;
    for (uint8_t i = 0; i < len; i++) {
        crc ^= d[i];
        for (uint8_t j = 0; j < 8; j++)
            crc = (crc & 1) ? (crc >> 1) ^ 0xA001 : crc >> 1;
    }
    return crc;
}

/* ------------------- Frame transmit --------------------- */
static void tx_frame(const uint8_t *d, uint8_t len) {
    uint16_t crc = modbus_crc(d, len);
    for (uint8_t i = 0; i < len; i++) uart_putc((char)d[i]);
    uart_putc((char)(crc & 0xFF));
    uart_putc((char)(crc >> 8));
}

static void tx_exception(uint8_t fc, uint8_t code) {
    uint8_t ex[3] = { SLAVE_ADDR, (uint8_t)(fc | 0x80), code };
    tx_frame(ex, 3);
    uart_puts("\r\n[EXC] fc=");
    uart_puthex8(fc);
    uart_puts(" code=");
    uart_puthex8(code);
    uart_puts("\r\n");
}

/* ------------------- Frame processor -------------------- */
static void handle_frame(const uint8_t *f, uint8_t len) {
    if (len < 8 || f[0] != SLAVE_ADDR) return;

    uint16_t rx_crc = (uint16_t)f[len - 1] << 8 | f[len - 2];
    if (modbus_crc(f, len - 2) != rx_crc) {
        uart_puts("\r\n[CRC-ERR]\r\n");
        return;
    }

    uint8_t fc = f[1];
    uint16_t addr = (uint16_t)f[2] << 8 | f[3];
    uint16_t cnt  = (uint16_t)f[4] << 8 | f[5];

    g_frame_count++;
    LED_PORT ^= (1 << LED_PIN);               /* activity LED */

    switch (fc) {
    case 0x03:                                /* Read Holding Registers */
    case 0x04: {                              /* Read Input Registers */
        uint8_t max_regs = (fc == 0x03) ? MB_HOLDING_REGS : MB_INPUT_REGS;
        if (cnt == 0 || cnt > 125 || (uint32_t)addr + cnt > max_regs) {
            tx_exception(fc, 0x02);
            return;
        }
        const uint16_t *src = (fc == 0x03) ? g_holding : g_inputs;
        uint8_t resp[3 + 250];
        resp[0] = SLAVE_ADDR;
        resp[1] = fc;
        resp[2] = cnt * 2;
        for (uint16_t i = 0; i < cnt; i++) {
            resp[3 + i * 2] = (uint8_t)(src[addr + i] >> 8);
            resp[4 + i * 2] = (uint8_t)src[addr + i];
        }
        tx_frame(resp, 3 + cnt * 2);
        uart_puts("\r\n[");
        uart_puthex8(fc);
        uart_puts("] reg=");
        uart_puthex16(addr);
        uart_puts(" cnt=");
        uart_putdec16(cnt);
        uart_puts(" bytes=");
        uart_putdec16(3 + cnt * 2);
        break;
    }
    case 0x06: {                              /* Write Single Register */
        uint16_t val = (uint16_t)f[4] << 8 | f[5];
        if (addr >= MB_HOLDING_REGS) {
            tx_exception(fc, 0x02);
            return;
        }
        g_holding[addr] = val;
        tx_frame(f, 6);                       /* echo request */
        uart_puts("\r\n[06] reg=");
        uart_puthex16(addr);
        uart_puts(" val=");
        uart_puthex16(val);
        break;
    }
    case 0x10: {                              /* Write Multiple Registers */
        uint8_t bc = f[6];
        if (cnt == 0 || cnt > 123 || bc != cnt * 2 ||
            (uint32_t)addr + cnt > MB_HOLDING_REGS) {
            tx_exception(fc, 0x02);
            return;
        }
        if (7 + bc + 2 > len) {
            tx_exception(fc, 0x03);
            return;
        }
        for (uint16_t i = 0; i < cnt; i++)
            g_holding[addr + i] = (uint16_t)f[7 + i * 2] << 8 | f[8 + i * 2];
        uint8_t resp[6] = { SLAVE_ADDR, 0x10, f[2], f[3], f[4], f[5] };
        tx_frame(resp, 6);
        uart_puts("\r\n[16] reg=");
        uart_puthex16(addr);
        uart_puts(" cnt=");
        uart_putdec16(cnt);
        break;
    }
    default:                                  /* Illegal function */
        tx_exception(fc, 0x01);
        break;
    }
    uart_puts("\r\n");
}

/* ------------------- Input registers -------------------- */
static void update_inputs(void) {
    g_inputs[0] = adc_read(0);
    g_inputs[1] = adc_read(1);
    g_inputs[2] = adc_read(2);
    g_inputs[3] = adc_read(3);
    g_inputs[4] = (uint16_t)(g_tick_ms & 0xFFFF);
    g_inputs[5] = (uint16_t)(g_frame_count & 0xFFFF);
}

/* ------------------------- main -------------------------- */
int main(void) {
    LED_DDR |= (1 << LED_PIN);
    LED_PORT &= ~(1 << LED_PIN);

    uart_init();
    timer_init();

    for (uint16_t i = 0; i < MB_HOLDING_REGS; i++)
        g_holding[i] = (i == 0) ? 0x1234 : (uint16_t)(1000 + i);
    g_inputs[6] = 0xCAFE;
    g_inputs[7] = 0;

    sei();

    uart_puts("\r\n=== Modbus RTU Slave (UNO) ===\r\n");
    uart_puts("Addr=1 FC:03/04/06/16 @9600 8N1\r\n");
    uart_puts("Hold=0x0000-0x001F In=0x0000-0x0007\r\n");

    uint16_t last_tick = 0;
    for (;;) {
        /* detect end-of-frame: no byte for >5ms */
        if (g_rx_head != g_rx_tail) {
            if ((uint32_t)(g_tick_ms - g_last_rx_ms) >= FRAME_TIMEOUT_MS) {
                uint8_t fbuf[MB_BUF_SZ], len = 0;
                while (g_rx_tail != g_rx_head && len < MB_BUF_SZ) {
                    fbuf[len++] = g_rx_buf[g_rx_tail];
                    g_rx_tail = (g_rx_tail + 1) % MB_BUF_SZ;
                }
                handle_frame(fbuf, len);
            }
        }
        /* refresh ADC-backed input registers every ~500ms */
        if ((uint16_t)(g_tick_ms - last_tick) >= 500) {
            last_tick = (uint16_t)g_tick_ms;
            update_inputs();
        }
    }
    return 0;
}
