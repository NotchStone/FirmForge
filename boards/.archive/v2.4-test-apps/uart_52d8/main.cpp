#include <Arduino.h>
/* FirmForge Boot Signature — AVR UART0 (TX=pin1, 9600) */
namespace {
struct _FirmForgeBoot {
    _FirmForgeBoot() {
        UBRR0H = (unsigned char)(103 >> 8);
        UBRR0L = (unsigned char)(103);
        UCSR0B = (1 << TXEN0);
        UCSR0C = (3 << UCSZ00);
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=52d8aef3\n";
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
#define ASCII_PRINTABLE_START 32   // 可打印字符起始 ASCII 码
#define ASCII_PRINTABLE_END   126  // 可打印字符结束 ASCII 码
#define SERIAL_BAUD_RATE      9600 // 串口波特率
#define PRINT_INTERVAL_MS     10000 // 打印间隔 (毫秒)

// 函数声明
void printAsciiTable(void);

// 全局变量
unsigned long lastPrintTime = 0; // 上次打印时间戳

void setup() {
    // 初始化串口通信
    Serial.begin(SERIAL_BAUD_RATE);
    
    // 等待串口就绪 (可选，对于 USB 虚拟串口有帮助)
    while (!Serial) {
        ; // 等待串口连接
    }
    
    // 打印启动信息
    Serial.println(F("ASCII Printable Table Printer"));
    Serial.print(F("Printing every "));
    Serial.print(PRINT_INTERVAL_MS / 1000);
    Serial.println(F(" seconds."));
    Serial.println();
    
    // 记录初始时间
    lastPrintTime = millis();
}

void loop() {
    unsigned long currentTime = millis();
    
    // 非阻塞定时: 每 PRINT_INTERVAL_MS 毫秒打印一次
    if (currentTime - lastPrintTime >= PRINT_INTERVAL_MS) {
        lastPrintTime = currentTime;
        printAsciiTable();
    }
}

/**
 * 打印完整的 ASCII 可打印字符表 (32 到 126)
 * 每行格式: "Decimal: {n} | Char: {c}"
 * 一次性输出所有行
 */
void printAsciiTable(void) {
    Serial.println(F("--- ASCII Printable Characters (32-126) ---"));
    
    for (int i = ASCII_PRINTABLE_START; i <= ASCII_PRINTABLE_END; i++) {
        Serial.print(F("Decimal: "));
        Serial.print(i);
        Serial.print(F(" | Char: "));
        Serial.write((char)i);  // 直接发送字符字节
        Serial.println();
    }
    
    Serial.println(F("--- End of Table ---"));
    Serial.println();
}