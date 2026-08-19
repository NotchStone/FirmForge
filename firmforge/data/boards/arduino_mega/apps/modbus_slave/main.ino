/* ============================================================
 * Modbus RTU Slave — Mega2560 (Arduino Serial API)
 * Uses Arduino Serial which properly initializes USART0 for
 * the specific board clock configuration.
 * ============================================================ */

#include <Arduino.h>

#define MB_SLAVE_ID   1
#define MB_REGS       100
#define MB_BUF_SZ     256

static uint16_t g_regs[MB_REGS];
static uint16_t g_inputs[MB_REGS];   /* FC04 input registers */
static uint8_t  g_rx[MB_BUF_SZ];
static uint16_t g_idx;
static unsigned long g_last_rx;   /* ms of last byte received (frame gap) */

void setup() {
    Serial.begin(9600);
    Serial.print("MB\r\n");  /* startup pulse */

    for (uint16_t i = 0; i < MB_REGS; i++) {
        g_regs[i] = 1000 + i;
        g_inputs[i] = 2000 + i;
    }
    g_idx = 0;
}

/* ---------- CRC-16 (Modbus) ---------- */
static uint16_t modbus_crc(const uint8_t *buf, uint16_t len) {
    uint16_t crc = 0xFFFF;
    for (uint16_t i = 0; i < len; i++) {
        crc ^= buf[i];
        for (uint8_t j = 0; j < 8; j++)
            crc = (crc & 1) ? (crc >> 1) ^ 0xA001 : crc >> 1;
    }
    return crc;
}

static void handle_frame(uint16_t len) {
    if (len < 4) return;
    if (g_rx[0] != MB_SLAVE_ID) return;

    uint16_t rx_crc = ((uint16_t)g_rx[len - 1] << 8) | g_rx[len - 2];  // CRC is low-byte-first
    if (modbus_crc(g_rx, len - 2) != rx_crc) return;

    uint8_t fc = g_rx[1];

    switch (fc) {
    case 0x03: { /* Read Holding Registers */
        uint16_t addr = (g_rx[2] << 8) | g_rx[3];
        uint16_t cnt  = (g_rx[4] << 8) | g_rx[5];
        if (addr + cnt > MB_REGS || cnt == 0 || cnt > 125) {
            uint8_t ex[3] = {MB_SLAVE_ID, 0x83, 0x02};
            uint16_t c = modbus_crc(ex, 3);
            Serial.write(ex, 3);
            Serial.write((uint8_t)(c & 0xFF));
            Serial.write((uint8_t)((c >> 8) & 0xFF));
            return;
        }
        Serial.write((uint8_t)MB_SLAVE_ID);
        Serial.write((uint8_t)0x03);
        Serial.write((uint8_t)(cnt * 2));
        for (uint16_t i = 0; i < cnt; i++) {
            Serial.write((uint8_t)((g_regs[addr + i] >> 8) & 0xFF));
            Serial.write((uint8_t)(g_regs[addr + i] & 0xFF));
        }
        /* CRC */
        uint8_t *p = g_rx; /* reuse buffer for response CRC calc */
        p[0] = MB_SLAVE_ID; p[1] = 0x03; p[2] = cnt * 2;
        for (uint16_t i = 0; i < cnt; i++) {
            p[3 + i*2] = (g_regs[addr + i] >> 8) & 0xFF;
            p[4 + i*2] = g_regs[addr + i] & 0xFF;
        }
        uint16_t c = modbus_crc(p, 3 + cnt * 2);
        Serial.write((uint8_t)(c & 0xFF));
        Serial.write((uint8_t)((c >> 8) & 0xFF));
        break;
    }
    case 0x04: { /* Read Input Registers */
        uint16_t addr = (g_rx[2] << 8) | g_rx[3];
        uint16_t cnt  = (g_rx[4] << 8) | g_rx[5];
        if (addr + cnt > MB_REGS || cnt == 0 || cnt > 125) {
            uint8_t ex[3] = {MB_SLAVE_ID, 0x84, 0x02};
            uint16_t c = modbus_crc(ex, 3);
            Serial.write(ex, 3);
            Serial.write((uint8_t)(c & 0xFF));
            Serial.write((uint8_t)((c >> 8) & 0xFF));
            return;
        }
        Serial.write((uint8_t)MB_SLAVE_ID);
        Serial.write((uint8_t)0x04);
        Serial.write((uint8_t)(cnt * 2));
        for (uint16_t i = 0; i < cnt; i++) {
            Serial.write((uint8_t)((g_inputs[addr + i] >> 8) & 0xFF));
            Serial.write((uint8_t)(g_inputs[addr + i] & 0xFF));
        }
        uint8_t *p = g_rx;
        p[0] = MB_SLAVE_ID; p[1] = 0x04; p[2] = cnt * 2;
        for (uint16_t i = 0; i < cnt; i++) {
            p[3 + i*2] = (g_inputs[addr + i] >> 8) & 0xFF;
            p[4 + i*2] = g_inputs[addr + i] & 0xFF;
        }
        uint16_t c = modbus_crc(p, 3 + cnt * 2);
        Serial.write((uint8_t)(c & 0xFF));
        Serial.write((uint8_t)((c >> 8) & 0xFF));
        break;
    }
    case 0x06: {
        uint16_t addr = (g_rx[2] << 8) | g_rx[3];
        uint16_t val  = (g_rx[4] << 8) | g_rx[5];
        if (addr >= MB_REGS) {
            uint8_t ex[3] = {MB_SLAVE_ID, 0x86, 0x02};
            uint16_t c = modbus_crc(ex, 3);
            Serial.write(ex, 3);
            Serial.write((uint8_t)(c & 0xFF));
            Serial.write((uint8_t)((c >> 8) & 0xFF));
            return;
        }
        g_regs[addr] = val;
        Serial.write(g_rx, 6);
        uint16_t c = modbus_crc(g_rx, 6);
        Serial.write((uint8_t)(c & 0xFF));
        Serial.write((uint8_t)((c >> 8) & 0xFF));
        break;
    }
    case 0x10: { /* Write Multiple Registers */
        uint16_t addr = (g_rx[2] << 8) | g_rx[3];
        uint16_t cnt  = (g_rx[4] << 8) | g_rx[5];
        uint8_t  bc   = g_rx[6];
        if (addr + cnt > MB_REGS || cnt == 0 || cnt > 123 || bc != cnt * 2) {
            uint8_t ex[3] = {MB_SLAVE_ID, 0x90, 0x02};
            uint16_t c = modbus_crc(ex, 3);
            Serial.write(ex, 3);
            Serial.write((uint8_t)(c & 0xFF));
            Serial.write((uint8_t)((c >> 8) & 0xFF));
            return;
        }
        for (uint16_t i = 0; i < cnt; i++)
            g_regs[addr + i] = (g_rx[7 + i*2] << 8) | g_rx[8 + i*2];
        /* Echo response: slave + fc + addr(2) + count(2) + crc(2) */
        uint8_t resp[8] = {MB_SLAVE_ID, 0x10, g_rx[2], g_rx[3], g_rx[4], g_rx[5], 0, 0};
        uint16_t c = modbus_crc(resp, 6);
        resp[6] = c & 0xFF; resp[7] = (c >> 8) & 0xFF;
        Serial.write(resp, 8);
        break;
    }
    default:
        break;
    }
}

void loop() {
    /* Frame-gap detection: process when no byte arrives for 5ms.
     * Bytes may arrive in bursts over USB — never drop a partial frame. */
    while ((UCSR0A & (1 << RXC0)) && g_idx < MB_BUF_SZ) {
        g_rx[g_idx++] = UDR0;
        g_last_rx = millis();
    }
    if (g_idx > 0 && (millis() - g_last_rx) > 5) {
        handle_frame(g_idx);
        g_idx = 0;
    }
}
