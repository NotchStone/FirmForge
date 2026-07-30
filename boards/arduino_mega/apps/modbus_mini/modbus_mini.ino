/* Minimal Modbus RTU Slave — just one holding register at addr 0 = 0x1234 */
#include <Arduino.h>

void setup() {
    Serial.begin(9600);
    Serial.print("OK\r\n");  // startup pulse
}

void loop() {
    if (Serial.available() < 8) return;  // wait for full frame

    // Read frame: slave(1) + fc(1) + addr(2) + count(2) + crc(2)
    uint8_t frame[8];
    for (int i = 0; i < 8; i++) frame[i] = Serial.read();

    // Only respond to slave 1, FC03, addr 0, count 1
    if (frame[0] != 1 || frame[1] != 3) return;
    if (frame[2] != 0 || frame[3] != 0) return;
    if (frame[4] != 0 || frame[5] != 1) return;

    // Build response: slave + fc + byte_count(2) + val_h + val_l + crc(2)
    uint8_t resp[] = {0x01, 0x03, 0x02, 0x12, 0x34, 0x00, 0x00};
    // CRC: poly 0xA001
    uint16_t crc = 0xFFFF;
    for (int i = 0; i < 5; i++) {
        crc ^= resp[i];
        for (int j = 0; j < 8; j++)
            crc = (crc & 1) ? (crc >> 1) ^ 0xA001 : crc >> 1;
    }
    resp[5] = crc & 0xFF;
    resp[6] = (crc >> 8) & 0xFF;

    Serial.write(resp, 7);
}
