#include <Arduino.h>
/* FirmForge Boot Signature — AVR UART0 (TX=pin1, 9600) */
namespace {
struct _FirmForgeBoot {
    _FirmForgeBoot() {
        UBRR0H = (unsigned char)(103 >> 8);
        UBRR0L = (unsigned char)(103);
        UCSR0B = (1 << TXEN0);
        UCSR0C = (3 << UCSZ00);
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=79ab27d9\n";
        for (const char* p = sig; *p; p++) {
            while (!(UCSR0A & (1 << UDRE0))) { }
            UDR0 = (unsigned char)(*p);
        }
    }
} _firmforge_boot;
}

// 串口计数器：每秒通过串口打印递增的计数值
// 波特率：9600 bps

// 计数器变量
static unsigned long counter = 0;

// 上次打印的时间戳（毫秒）
static unsigned long lastPrintTime = 0;

// 打印间隔（毫秒）
#define PRINT_INTERVAL_MS 1000

void setup() {
    // 初始化串口通信，波特率 9600
    Serial.begin(9600);
    
    // 等待串口稳定（可选，对于 USB 虚拟串口建议）
    while (!Serial) {
        ; // 等待串口连接（仅适用于 Leonardo/Micro 等板，UNO 上无影响）
    }
    
    // 打印初始消息
    Serial.println("Serial Counter Started");
    
    // 记录起始时间
    lastPrintTime = millis();
}

void loop() {
    // 获取当前时间
    unsigned long currentTime = millis();
    
    // 检查是否到达打印间隔
    if (currentTime - lastPrintTime >= PRINT_INTERVAL_MS) {
        // 更新上次打印时间
        lastPrintTime = currentTime;
        
        // 打印当前计数值并递增
        Serial.print("Counter: ");
        Serial.println(counter);
        counter++;
    }
    
    // 可在此处添加其他非阻塞任务
    // 例如：检查串口输入、读取传感器等
}