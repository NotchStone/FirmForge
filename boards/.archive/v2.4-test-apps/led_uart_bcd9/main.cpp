#include <Arduino.h>
/* FirmForge Boot Signature — AVR UART0 (TX=pin1, 9600) */
namespace {
struct _FirmForgeBoot {
    _FirmForgeBoot() {
        UBRR0H = (unsigned char)(103 >> 8);
        UBRR0L = (unsigned char)(103);
        UCSR0B = (1 << TXEN0);
        UCSR0C = (3 << UCSZ00);
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=bcd98aa3\n";
        for (const char* p = sig; *p; p++) {
            while (!(UCSR0A & (1 << UDRE0))) { }
            UDR0 = (unsigned char)(*p);
        }
    }
} _firmforge_boot;
}

/*============================================================================
 * 常量定义
 *============================================================================*/
#define LED_PIN         13          /* 板载 LED 引脚 (PB7) */
#define SERIAL_BAUD     9600        /* 串口波特率 */
#define BLINK_INTERVAL  200         /* LED 闪烁间隔 (ms) */
#define PRINT_INTERVAL  1000        /* 串口打印间隔 (ms) */

/*============================================================================
 * 模块: led_blink
 * 功能: 控制板载 LED 以 200ms 间隔闪烁
 * 依赖: 无
 *============================================================================*/

/**
 * @brief 初始化 LED 引脚为输出模式
 */
static void led_blink_init(void)
{
    pinMode(LED_PIN, OUTPUT);
    digitalWrite(LED_PIN, LOW);     /* 初始状态熄灭 */
}

/**
 * @brief 切换 LED 状态（非阻塞）
 * @note  由主循环定时调用，每次调用翻转一次电平
 */
static void led_blink_toggle(void)
{
    static uint8_t led_state = LOW;
    led_state = (led_state == LOW) ? HIGH : LOW;
    digitalWrite(LED_PIN, led_state);
}

/*============================================================================
 * 模块: uart_driver
 * 功能: 通过串口每 1 秒打印 "HELLO"
 * 依赖: 无
 *============================================================================*/

/**
 * @brief 初始化串口通信
 */
static void uart_driver_init(void)
{
    Serial.begin(SERIAL_BAUD);
    /* 等待串口稳定（可选，对 USB 虚拟串口有意义） */
    while (!Serial) {
        delay(10);
    }
}

/**
 * @brief 打印一次 "HELLO" 字符串
 */
static void uart_driver_print_hello(void)
{
    Serial.println("HELLO");
}

/*============================================================================
 * 主程序
 *============================================================================*/

/**
 * @brief Arduino setup 函数：初始化所有模块
 */
void setup(void)
{
    led_blink_init();
    uart_driver_init();
}

/**
 * @brief Arduino loop 函数：非阻塞调度两个任务
 *
 * 调度策略：
 *   - LED 闪烁：每 200ms 翻转一次
 *   - 串口打印：每 1000ms 打印一次 "HELLO"
 *
 * 使用 millis() 实现非阻塞定时，避免 delay() 阻塞 CPU。
 */
void loop(void)
{
    static unsigned long last_blink_time = 0;
    static unsigned long last_print_time = 0;
    unsigned long current_time = millis();

    /* ---- 任务 1: LED 闪烁 (200ms) ---- */
    if (current_time - last_blink_time >= BLINK_INTERVAL) {
        last_blink_time = current_time;
        led_blink_toggle();
    }

    /* ---- 任务 2: 串口打印 (1000ms) ---- */
    if (current_time - last_print_time >= PRINT_INTERVAL) {
        last_print_time = current_time;
        uart_driver_print_hello();
    }
}