#include <Arduino.h>
/* FirmForge Boot Signature — AVR UART0 (TX=pin1, 9600) */
namespace {
struct _FirmForgeBoot {
    _FirmForgeBoot() {
        UBRR0H = (unsigned char)(103 >> 8);
        UBRR0L = (unsigned char)(103);
        UCSR0B = (1 << TXEN0);
        UCSR0C = (3 << UCSZ00);
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=1f6fccdb\n";
        for (const char* p = sig; *p; p++) {
            while (!(UCSR0A & (1 << UDRE0))) { }
            UDR0 = (unsigned char)(*p);
        }
    }
} _firmforge_boot;
}

/*============================================================================
 * 模块: LED 闪烁 (led_blink)
 * 功能: 以 200ms 间隔切换板载 LED 状态
 * 引脚: LED_BUILTIN (Arduino 引脚 13, PB7)
 * 周期: 200ms 亮, 200ms 灭
 *============================================================================*/

/**
 * @brief 初始化 LED 引脚为输出模式
 */
static void led_blink_init(void)
{
    pinMode(LED_BUILTIN, OUTPUT);
    digitalWrite(LED_BUILTIN, LOW);  /* 初始状态: 熄灭 */
}

/**
 * @brief 执行一次 LED 状态切换
 * @note  非阻塞: 使用 millis() 实现定时切换
 */
static void led_blink_update(void)
{
    static unsigned long last_toggle = 0;
    const unsigned long now = millis();
    const unsigned long interval = 200;  /* 200ms 闪烁间隔 */

    if (now - last_toggle >= interval) {
        last_toggle = now;
        digitalWrite(LED_BUILTIN, !digitalRead(LED_BUILTIN));
    }
}

/*============================================================================
 * 模块: UART 通信 (uart_driver)
 * 功能: 通过串口以 9600 波特率发送 "HELLO" 字符串
 * 引脚: TX=引脚1 (PD1), RX=引脚0 (PD0)
 * 周期: 每 2 秒发送一次
 *============================================================================*/

/**
 * @brief 初始化 UART 串口
 * @note  波特率 9600, 8N1 格式
 */
static void uart_driver_init(void)
{
    Serial.begin(9600);
    /* 等待串口就绪 (可选, 对 USB 虚拟串口有意义) */
    while (!Serial) {
        delay(10);
    }
}

/**
 * @brief 定时发送 "HELLO" 字符串
 * @note  非阻塞: 使用 millis() 控制发送间隔
 */
static void uart_driver_update(void)
{
    static unsigned long last_send = 0;
    const unsigned long now = millis();
    const unsigned long send_interval = 2000;  /* 每 2 秒发送一次 */

    if (now - last_send >= send_interval) {
        last_send = now;
        Serial.println("HELLO");
    }
}

/*============================================================================
 * 主程序: Arduino setup() + loop()
 *============================================================================*/

/**
 * @brief Arduino 初始化函数
 * - 初始化 LED 闪烁模块
 * - 初始化 UART 通信模块
 */
void setup(void)
{
    led_blink_init();
    uart_driver_init();
}

/**
 * @brief Arduino 主循环函数
 * - 更新 LED 闪烁状态 (200ms 周期)
 * - 更新 UART 发送状态 (2s 周期)
 */
void loop(void)
{
    led_blink_update();
    uart_driver_update();
}