#include <Arduino.h>
/* FirmForge Boot Signature — AVR UART0 (TX=pin1, 9600) */
namespace {
struct _FirmForgeBoot {
    _FirmForgeBoot() {
        UBRR0H = (unsigned char)(103 >> 8);
        UBRR0L = (unsigned char)(103);
        UCSR0B = (1 << TXEN0);
        UCSR0C = (3 << UCSZ00);
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=71099bd6\n";
        for (const char* p = sig; *p; p++) {
            while (!(UCSR0A & (1 << UDRE0))) { }
            UDR0 = (unsigned char)(*p);
        }
    }
} _firmforge_boot;
}

/*============================================================================
 * 模块: led_blink (LED 闪烁)
 * 功能: 控制板载 LED 以 200ms 间隔闪烁
 * 引脚: LED_BUILTIN (Arduino 引脚 13)
 * 依赖: 无
 *============================================================================*/

/**
 * @brief 初始化 LED 引脚为输出模式
 */
void led_blink_init(void)
{
    pinMode(LED_BUILTIN, OUTPUT);
    digitalWrite(LED_BUILTIN, LOW);  // 初始状态熄灭
}

/**
 * @brief 切换 LED 状态 (非阻塞)
 * @note 调用间隔应为 200ms 以实现 200ms 闪烁周期
 */
void led_blink_toggle(void)
{
    static uint8_t led_state = LOW;
    led_state = (led_state == LOW) ? HIGH : LOW;
    digitalWrite(LED_BUILTIN, led_state);
}

/*============================================================================
 * 模块: uart_driver (UART 通信)
 * 功能: 通过串口以 9600 波特率发送 "HELLO" 字符串
 * 引脚: TX=引脚1, RX=引脚0
 * 依赖: 无
 *============================================================================*/

/**
 * @brief 初始化 UART 串口通信
 * @param baud_rate 波特率 (推荐 9600)
 */
void uart_driver_init(unsigned long baud_rate)
{
    Serial.begin(baud_rate);
    while (!Serial) {
        ;  // 等待串口就绪 (仅适用于原生 USB 板，此处保留兼容性)
    }
}

/**
 * @brief 发送 "HELLO" 字符串到串口
 */
void uart_driver_send_hello(void)
{
    Serial.println("HELLO");
}

/*============================================================================
 * 主程序
 * 调度模式: auto (自动调度)
 * 功能点数: 2
 *   - LED 闪烁 (200ms 间隔)
 *   - UART 通信 (每 2s 发送 "HELLO")
 *============================================================================*/

// 时间常量 (单位: 毫秒)
#define LED_BLINK_INTERVAL_MS   200UL
#define UART_HELLO_INTERVAL_MS  2000UL

// 上次执行时间戳
static unsigned long last_led_toggle_ms = 0;
static unsigned long last_uart_hello_ms = 0;

/**
 * @brief Arduino setup 函数: 初始化所有模块
 */
void setup(void)
{
    led_blink_init();
    uart_driver_init(9600);
}

/**
 * @brief Arduino loop 函数: 非阻塞调度任务
 * @note 使用 millis() 实现时间触发，避免 delay() 阻塞
 */
void loop(void)
{
    unsigned long current_ms = millis();

    /* 任务 1: LED 闪烁 (每 200ms 切换一次) */
    if (current_ms - last_led_toggle_ms >= LED_BLINK_INTERVAL_MS) {
        last_led_toggle_ms = current_ms;
        led_blink_toggle();
    }

    /* 任务 2: UART 发送 "HELLO" (每 2s 发送一次) */
    if (current_ms - last_uart_hello_ms >= UART_HELLO_INTERVAL_MS) {
        last_uart_hello_ms = current_ms;
        uart_driver_send_hello();
    }
}