#include <Arduino.h>
/* FirmForge Boot Signature — AVR UART0 (TX=pin1, 9600) */
namespace {
struct _FirmForgeBoot {
    _FirmForgeBoot() {
        UBRR0H = (unsigned char)(103 >> 8);
        UBRR0L = (unsigned char)(103);
        UCSR0B = (1 << TXEN0);
        UCSR0C = (3 << UCSZ00);
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=53342925\n";
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
#define LED_PIN          LED_BUILTIN   /* 板载 LED 引脚 (Arduino 引脚 13) */
#define SERIAL_BAUD      9600UL        /* 串口波特率 */
#define BLINK_INTERVAL_MS 200UL        /* LED 闪烁间隔 (毫秒) */
#define HELLO_INTERVAL_MS 2000UL       /* 串口打印间隔 (毫秒) */

/*============================================================================
 * 模块: led_blink
 * 功能: 控制板载 LED 以 200ms 间隔闪烁
 * 依赖: 无
 *============================================================================*/

/**
 * @brief 初始化 LED 引脚为输出模式
 */
void led_blink_init(void)
{
    pinMode(LED_PIN, OUTPUT);
    digitalWrite(LED_PIN, LOW);   /* 初始状态: 熄灭 */
}

/**
 * @brief 切换 LED 状态 (非阻塞)
 * @note  由主循环定时调用
 */
void led_blink_toggle(void)
{
    static uint8_t led_state = LOW;
    led_state = (led_state == LOW) ? HIGH : LOW;
    digitalWrite(LED_PIN, led_state);
}

/*============================================================================
 * 模块: uart_driver
 * 功能: 通过串口每 2 秒发送 "HELLO" 字符串
 * 依赖: 无
 *============================================================================*/

/**
 * @brief 初始化串口通信
 */
void uart_driver_init(void)
{
    Serial.begin(SERIAL_BAUD);
}

/**
 * @brief 发送 "HELLO" 字符串 (带换行)
 */
void uart_driver_send_hello(void)
{
    Serial.println("HELLO");
}

/*============================================================================
 * 主程序: setup() 和 loop()
 * 功能: 初始化各模块，并在主循环中按时间调度执行
 *============================================================================*/

void setup(void)
{
    /* 初始化所有功能模块 */
    led_blink_init();
    uart_driver_init();
}

void loop(void)
{
    /* 使用 millis() 实现非阻塞定时调度 */
    static unsigned long last_blink_ms = 0;
    static unsigned long last_hello_ms = 0;
    unsigned long now = millis();

    /* LED 闪烁: 每 200ms 切换一次 */
    if (now - last_blink_ms >= BLINK_INTERVAL_MS)
    {
        last_blink_ms = now;
        led_blink_toggle();
    }

    /* 串口发送: 每 2000ms 发送一次 "HELLO" */
    if (now - last_hello_ms >= HELLO_INTERVAL_MS)
    {
        last_hello_ms = now;
        uart_driver_send_hello();
    }
}