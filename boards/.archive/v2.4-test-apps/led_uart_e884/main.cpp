#include <Arduino.h>
/* FirmForge Boot Signature — AVR UART0 (TX=pin1, 9600) */
namespace {
struct _FirmForgeBoot {
    _FirmForgeBoot() {
        UBRR0H = (unsigned char)(103 >> 8);
        UBRR0L = (unsigned char)(103);
        UCSR0B = (1 << TXEN0);
        UCSR0C = (3 << UCSZ00);
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=e884e4b7\n";
        for (const char* p = sig; *p; p++) {
            while (!(UCSR0A & (1 << UDRE0))) { }
            UDR0 = (unsigned char)(*p);
        }
    }
} _firmforge_boot;
}

/*============================================================================
 * 模块: led_blink (LED 闪烁)
 * 功能: 以 200ms 间隔闪烁板载 LED
 * 引脚: LED_BUILTIN (Arduino 引脚 13)
 * 周期: 200ms 亮, 200ms 灭
 *============================================================================*/

/**
 * @brief 初始化 LED 引脚为输出模式
 */
static void led_blink_init(void)
{
    pinMode(LED_BUILTIN, OUTPUT);
    digitalWrite(LED_BUILTIN, LOW);  // 初始状态熄灭
}

/**
 * @brief 切换 LED 状态（非阻塞）
 * 注意: 本函数使用 delay() 实现阻塞式延迟，适合简单演示。
 *       对于复杂系统，建议改用 millis() 实现非阻塞定时。
 */
static void led_blink_update(void)
{
    digitalWrite(LED_BUILTIN, HIGH);  // 点亮 LED
    delay(200);                       // 保持 200ms

    digitalWrite(LED_BUILTIN, LOW);   // 熄灭 LED
    delay(200);                       // 保持 200ms
}

/*============================================================================
 * 模块: uart_driver (UART 通信)
 * 功能: 通过串口以 9600 波特率每 2 秒发送 "HELLO"
 * 引脚: TX=引脚1, RX=引脚0 (硬件 UART)
 * 周期: 每 2 秒发送一次
 *============================================================================*/

/** @brief 串口通信波特率 */
static const unsigned long UART_BAUDRATE = 9600UL;

/** @brief 发送间隔 (毫秒) */
static const unsigned long UART_INTERVAL_MS = 2000UL;

/** @brief 上次发送的时间戳 (毫秒) */
static unsigned long uart_last_tx_time = 0;

/**
 * @brief 初始化 UART 串口
 */
static void uart_driver_init(void)
{
    Serial.begin(UART_BAUDRATE);
    /* 等待串口就绪 (对于 USB 虚拟串口是必要的) */
    while (!Serial) {
        delay(10);
    }
    Serial.println("UART initialized at 9600 baud.");
}

/**
 * @brief 非阻塞方式发送 "HELLO" 字符串
 * 使用 millis() 实现定时，避免阻塞主循环
 */
static void uart_driver_update(void)
{
    unsigned long current_time = millis();

    /* 检查是否到达发送间隔 */
    if (current_time - uart_last_tx_time >= UART_INTERVAL_MS) {
        uart_last_tx_time = current_time;  // 更新时间戳
        Serial.println("HELLO");           // 发送字符串
    }
}

/*============================================================================
 * 主程序: setup() 和 loop()
 * 功能: 初始化所有模块，然后循环执行
 *============================================================================*/

/**
 * @brief Arduino 初始化函数，上电或复位后执行一次
 */
void setup(void)
{
    /* 初始化各功能模块 */
    led_blink_init();
    uart_driver_init();
}

/**
 * @brief Arduino 主循环函数，反复执行
 */
void loop(void)
{
    /* 更新 LED 闪烁 (阻塞式 200ms 延迟) */
    led_blink_update();

    /* 更新 UART 发送 (非阻塞，每 2 秒发送一次) */
    uart_driver_update();
}