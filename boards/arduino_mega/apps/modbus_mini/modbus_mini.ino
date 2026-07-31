/* Modbus RTU Slave — FC03 read holding registers, addr 0~99, count 1~125 */
#include <Arduino.h>

void setup() {
    Serial.begin(9600);
    Serial.print("OK\r\n");
}

void loop() {
    if (Serial.available() < 8) return;

    uint8_t frame[8];
    for (int i = 0; i < 8; i++) frame[i] = Serial.read();

    if (frame[0] != 1 || frame[1] != 3) return;

    uint16_t addr  = (frame[2] << 8) | frame[3];
    uint16_t count = (frame[4] << 8) | frame[5];
    if (count == 0 || count > 20) return;  // limit for safety

    // Build response: slave + fc + byte_count + data[count*2] + crc
    uint8_t resp[3 + 40 + 2];  // max 20 regs * 2 + header
    resp[0] = 0x01;
    resp[1] = 0x03;
    resp[2] = count * 2;
    for (uint16_t i = 0; i < count; i++) {
        uint16_t val = 1000 + addr + i;
        resp[3 + i * 2]     = (val >> 8) & 0xFF;
        resp[4 + i * 2]     = val & 0xFF;
    }
    uint16_t len = 3 + count * 2;
    // CRC
    uint16_t crc = 0xFFFF;
    for (uint16_t i = 0; i < len; i++) {
        crc ^= resp[i];
        for (int j = 0; j < 8; j++)
            crc = (crc & 1) ? (crc >> 1) ^ 0xA001 : crc >> 1;
    }
    resp[len]     = crc & 0xFF;
    resp[len + 1] = (crc >> 8) & 0xFF;

    Serial.write(resp, len + 2);
}
