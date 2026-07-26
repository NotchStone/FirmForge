#include <Arduino.h>
/* FirmForge Boot Signature — AVR UART0 (TX=pin1, 9600) */
namespace {
struct _FirmForgeBoot {
    _FirmForgeBoot() {
        UBRR0H = (unsigned char)(103 >> 8);
        UBRR0L = (unsigned char)(103);
        UCSR0B = (1 << TXEN0);
        UCSR0C = (3 << UCSZ00);
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=b211eeea\n";
        for (const char* p = sig; *p; p++) {
            while (!(UCSR0A & (1 << UDRE0))) { }
            UDR0 = (unsigned char)(*p);
        }
    }
} _firmforge_boot;
}

// 功能: 打印 ASCII 可打印字符表 (32-126)
// 每 10 秒通过串口输出一次完整表格
// 每行格式: "Decimal: {n} | Char: {c}"

// 常量定义
#define ASCII_PRINTABLE_START 32   // 可打印字符起始 (空格)
#define ASCII_PRINTABLE_END   126  // 可打印字符结束 (波浪号 ~)
#define PRINT_INTERVAL_MS     10000UL // 打印间隔 10 秒
#define SERIAL_BAUD_RATE      9600    // 串口波特率

// 函数声明
void printAsciiTable(void);

void setup() {
    // 初始化串口通信，波特率 9600
    Serial.begin(SERIAL_BAUD_RATE);
    
    // 等待串口稳定（可选，对于 USB 虚拟串口建议）
    while (!Serial) {
        ; // 等待串口连接（仅适用于 Leonardo/Micro 等，但保留兼容性）
    }
    
    // 首次启动时立即打印一次表格
    printAsciiTable();
}

void loop() {
    // 每 10 秒打印一次 ASCII 表格
    delay(PRINT_INTERVAL_MS);
    printAsciiTable();
}

/**
 * 打印完整的 ASCII 可打印字符表 (32-126)
 * 每行格式: "Decimal: {n} | Char: {c}"
 */
void printAsciiTable(void) {
    // 打印表头
    Serial.println("=== ASCII Printable Characters Table ===");
    Serial.println("Decimal | Char");
    Serial.println("--------|-----");
    
    // 遍历所有可打印字符
    for (int i = ASCII_PRINTABLE_START; i <= ASCII_PRINTABLE_END; i++) {
        // 打印十进制值和对应字符
        Serial.print("Decimal: ");
        Serial.print(i);
        Serial.print(" | Char: ");
        Serial.write((char)i);  // 使用 write 直接输出字符，避免 print 的格式化
        Serial.println();
    }
    
    // 打印结束分隔线
    Serial.println("========================================");
}