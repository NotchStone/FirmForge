/* Modbus RTU Slave — Arduino style (Serial API), ATmega328P (NANO)
 * FC03/04/06/16. Focus: FC06 (write single) / FC16 (write multiple).
 * reg[0]=0x1234 fixed flag; hold regs 1000+i; input regs 2000+i.
 */
#include <Arduino.h>

#define MB_REGS   100
#define MB_BUF_SZ 64

static uint16_t g_regs[MB_REGS];
static uint16_t g_inputs[MB_REGS];
static uint8_t  g_rx[MB_BUF_SZ];
static uint16_t g_idx;
static unsigned long g_last_rx;

void setup() {
    Serial.begin(9600);
    Serial.print("OK\r\n");
    for (uint16_t i = 0; i < MB_REGS; i++) {
        g_regs[i] = 1000 + i;
        g_inputs[i] = 2000 + i;
    }
    g_regs[0] = 0x1234;
    g_idx = 0;
}

static uint16_t modbus_crc(const uint8_t *buf, uint16_t len) {
    uint16_t crc = 0xFFFF;
    for (uint16_t i = 0; i < len; i++) {
        crc ^= buf[i];
        for (uint8_t j = 0; j < 8; j++)
            crc = (crc & 1) ? (crc >> 1) ^ 0xA001 : crc >> 1;
    }
    return crc;
}

static void send_exception(uint8_t fc, uint8_t code) {
    uint8_t ex[3] = {0x01, (uint8_t)(fc | 0x80), code};
    uint16_t c = modbus_crc(ex, 3);
    Serial.write(ex, 3);
    Serial.write((uint8_t)(c & 0xFF));
    Serial.write((uint8_t)((c >> 8) & 0xFF));
}

static void handle_frame(uint16_t len) {
    if (len < 8) return;
    if (g_rx[0] != 1) return;
    uint16_t rx_crc = ((uint16_t)g_rx[len - 1] << 8) | g_rx[len - 2];
    if (modbus_crc(g_rx, len - 2) != rx_crc) return;

    uint8_t fc = g_rx[1];
    uint16_t addr = (g_rx[2] << 8) | g_rx[3];
    uint16_t cnt  = (g_rx[4] << 8) | g_rx[5];

    switch (fc) {
    case 0x03: case 0x04: { /* Read Holding / Input */
        if (cnt == 0 || cnt > 20 || addr + cnt > MB_REGS) {
            send_exception(fc, 0x02);
            return;
        }
        const uint16_t *src = (fc == 0x03) ? g_regs : g_inputs;
        uint8_t resp[3 + 40];
        resp[0] = 0x01; resp[1] = fc; resp[2] = cnt * 2;
        for (uint16_t i = 0; i < cnt; i++) {
            resp[3 + i*2] = (src[addr + i] >> 8) & 0xFF;
            resp[4 + i*2] = src[addr + i] & 0xFF;
        }
        Serial.write(resp, 3 + cnt * 2);
        uint16_t full = modbus_crc(resp, 3 + cnt * 2);
        Serial.write((uint8_t)(full & 0xFF));
        Serial.write((uint8_t)((full >> 8) & 0xFF));
        break;
    }
    case 0x06: { /* Write Single Register */
        if (addr >= MB_REGS) { send_exception(fc, 0x02); return; }
        uint16_t val = (g_rx[4] << 8) | g_rx[5];
        g_regs[addr] = val;
        uint8_t resp[8];
        memcpy(resp, g_rx, 6);
        uint16_t c = modbus_crc(resp, 6);
        resp[6] = c & 0xFF; resp[7] = (c >> 8) & 0xFF;
        Serial.write(resp, 8);
        break;
    }
    case 0x10: { /* Write Multiple Registers */
        uint8_t bc = g_rx[6];
        if (cnt == 0 || cnt > 20 || addr + cnt > MB_REGS || bc != cnt * 2) {
            send_exception(fc, 0x02);
            return;
        }
        for (uint16_t i = 0; i < cnt; i++)
            g_regs[addr + i] = (g_rx[7 + i*2] << 8) | g_rx[8 + i*2];
        uint8_t resp[8] = {0x01, 0x10, g_rx[2], g_rx[3], g_rx[4], g_rx[5], 0, 0};
        uint16_t c = modbus_crc(resp, 6);
        resp[6] = c & 0xFF; resp[7] = (c >> 8) & 0xFF;
        Serial.write(resp, 8);
        break;
    }
    default:
        send_exception(fc, 0x01);
        break;
    }
}

void loop() {
    while (Serial.available() > 0 && g_idx < MB_BUF_SZ) {
        g_rx[g_idx++] = Serial.read();
        g_last_rx = millis();
    }
    if (g_idx > 0 && (millis() - g_last_rx) > 5) {
        handle_frame(g_idx);
        g_idx = 0;
    }
}
