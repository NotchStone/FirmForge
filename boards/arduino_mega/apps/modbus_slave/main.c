#define F_CPU 16000000UL
#include <avr/io.h>
#include <avr/interrupt.h>
#include <util/delay.h>
#include <string.h>

/* ============================================================
 * Modbus RTU Slave — Mega2560
 * Slave ID: 1
 * Holding Registers: 0x0000 ~ 0x0063 (100 registers)
 * FC03 Read Holding Registers
 * FC06 Write Single Register
 * FC16 Write Multiple Registers
 * ============================================================ */

#define MB_SLAVE_ID   1
#define MB_REGS       100
#define MB_BUF_SZ     256
#define MB_TIMEOUT_MS 10        /* 3.5 char time @ 9600 ~= 4ms */

static uint16_t g_regs[MB_REGS];
static uint8_t  g_rx[MB_BUF_SZ];
static volatile uint16_t g_rx_idx;

/* ---------- UART ---------- */
static void uart_init(void) {
    UBRR0H = 0; UBRR0L = 103;  /* 9600 @ 16MHz */
    UCSR0B = (1 << RXEN0) | (1 << TXEN0) | (1 << RXCIE0);
    UCSR0C = (1 << UCSZ01) | (1 << UCSZ00);
}
static void uart_byte(uint8_t b) {
    while (!(UCSR0A & (1 << UDRE0)));
    UDR0 = b;
}
static void uart_send(const uint8_t *buf, uint16_t len) {
    for (uint16_t i = 0; i < len; i++) uart_byte(buf[i]);
}

/* ---------- CRC-16 (Modbus) ---------- */
static uint16_t mb_crc(const uint8_t *buf, uint16_t len) {
    uint16_t crc = 0xFFFF;
    for (uint16_t i = 0; i < len; i++) {
        crc ^= buf[i];
        for (uint8_t j = 0; j < 8; j++)
            crc = (crc & 1) ? (crc >> 1) ^ 0xA001 : crc >> 1;
    }
    return crc;
}
static void append_crc(uint8_t *buf, uint16_t len) {
    uint16_t c = mb_crc(buf, len);
    buf[len] = c & 0xFF;
    buf[len + 1] = (c >> 8) & 0xFF;
}

/* ---------- Rx ISR ---------- */
ISR(USART0_RX_vect) {
    uint8_t b = UDR0;
    if (g_rx_idx < MB_BUF_SZ)
        g_rx[g_rx_idx++] = b;
}

/* ---------- Frame handler ---------- */
static void process_frame(uint16_t len) {
    if (len < 4) return;
    uint8_t slave = g_rx[0];
    uint8_t fc    = g_rx[1];

    if (slave != MB_SLAVE_ID) return;

    /* CRC check */
    uint16_t rx_crc = g_rx[len - 1] | ((uint16_t)g_rx[len - 2] << 8);
    if (mb_crc(g_rx, len - 2) != rx_crc) return;

    uint8_t resp[MB_BUF_SZ];
    uint16_t rlen = 0;

    switch (fc) {
    case 0x03: { /* Read Holding Registers */
        uint16_t addr = ((uint16_t)g_rx[2] << 8) | g_rx[3];
        uint16_t cnt  = ((uint16_t)g_rx[4] << 8) | g_rx[5];
        if (addr + cnt > MB_REGS || cnt == 0) {
            resp[0] = slave; resp[1] = 0x83; resp[2] = 0x02;
            rlen = 3; append_crc(resp, rlen); rlen += 2;
            uart_send(resp, rlen); return;
        }
        resp[0] = slave; resp[1] = 0x03;
        resp[2] = cnt * 2;
        for (uint16_t i = 0; i < cnt; i++) {
            resp[3 + i * 2]     = (g_regs[addr + i] >> 8) & 0xFF;
            resp[4 + i * 2]     = g_regs[addr + i] & 0xFF;
        }
        rlen = 3 + cnt * 2;
        append_crc(resp, rlen); rlen += 2;
        uart_send(resp, rlen);
        break;
    }
    case 0x06: { /* Write Single Register */
        uint16_t addr = ((uint16_t)g_rx[2] << 8) | g_rx[3];
        uint16_t val  = ((uint16_t)g_rx[4] << 8) | g_rx[5];
        if (addr >= MB_REGS) {
            resp[0] = slave; resp[1] = 0x86; resp[2] = 0x02;
            rlen = 3; append_crc(resp, rlen); rlen += 2;
            uart_send(resp, rlen); return;
        }
        g_regs[addr] = val;
        /* Echo same frame as response */
        memcpy(resp, g_rx, 6);
        rlen = 6; append_crc(resp, rlen); rlen += 2;
        uart_send(resp, rlen);
        break;
    }
    case 0x10: { /* Write Multiple Registers */
        uint16_t addr = ((uint16_t)g_rx[2] << 8) | g_rx[3];
        uint16_t cnt  = ((uint16_t)g_rx[4] << 8) | g_rx[5];
        if (addr + cnt > MB_REGS || cnt == 0) {
            resp[0] = slave; resp[1] = 0x90; resp[2] = 0x02;
            rlen = 3; append_crc(resp, rlen); rlen += 2;
            uart_send(resp, rlen); return;
        }
        for (uint16_t i = 0; i < cnt; i++)
            g_regs[addr + i] = ((uint16_t)g_rx[7 + i * 2] << 8) | g_rx[8 + i * 2];
        resp[0] = slave; resp[1] = 0x10;
        resp[2] = g_rx[2]; resp[3] = g_rx[3];
        resp[4] = g_rx[4]; resp[5] = g_rx[5];
        rlen = 6; append_crc(resp, rlen); rlen += 2;
        uart_send(resp, rlen);
        break;
    }
    default: {
        resp[0] = slave; resp[1] = fc | 0x80; resp[2] = 0x01;
        rlen = 3; append_crc(resp, rlen); rlen += 2;
        uart_send(resp, rlen);
        break;
    }
    }
}

/* ---------- Main ---------- */
int main(void) {
    uart_init();
    /* Init registers with known values */
    for (uint16_t i = 0; i < MB_REGS; i++)
        g_regs[i] = 1000 + i;
    sei();

    while (1) {
        if (g_rx_idx > 0) {
            /* Wait for frame gap = timeout */
            uint16_t saved = g_rx_idx;
            _delay_ms(MB_TIMEOUT_MS);
            /* Use timer-based idle detection: no new bytes = frame complete */
            if (g_rx_idx == saved && saved > 0) {
                process_frame(saved);
                g_rx_idx = 0;
            }
        }
    }
    return 0;
}
