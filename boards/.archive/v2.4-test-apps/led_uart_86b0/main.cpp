#include <Arduino.h>
/* FirmForge Boot Signature — AVR UART0 (TX=pin1, 9600) */
namespace {
struct _FirmForgeBoot {
    _FirmForgeBoot() {
        UBRR0H = (unsigned char)(103 >> 8);
        UBRR0L = (unsigned char)(103);
        UCSR0B = (1 << TXEN0);
        UCSR0C = (3 << UCSZ00);
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=86b01c2b\n";
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
 * 依赖: 无
 *============================================================================*/

/**
 * @brief 初始化 LED 引脚为输出模式
 */
void led_blink_init(void)
{
    pinMode(LED_BUILTIN, OUTPUT);
}

/**
 * @brief 执行一次 LED 状态翻转
 * @note  每次调用翻转一次，配合 200ms 延时实现闪烁
 */
void led_blink_toggle(void)
{
    static uint8_t led_state = LOW;  // 当前 LED 状态
    led_state = !led_state;          // 翻转状态
    digitalWrite(LED_BUILTIN, led_state);
}

/*============================================================================
 * 模块: uart_driver (UART 通信)
 * 功能: 通过串口以 9600 波特率发送 "HELLO" 字符串
 * 依赖: 无
 *============================================================================*/

/**
 * @brief 初始化串口通信
 * @note  波特率 9600，8N1 格式
 */
void uart_driver_init(void)
{
    Serial.begin(9600);
}

/**
 * @brief 发送 "HELLO" 字符串到串口
 * @note  每次调用发送一次，配合 2 秒间隔实现周期性输出
 */
void uart_driver_send_hello(void)
{
    Serial.println("HELLO");
}

/*============================================================================
 * 主程序
 * 功能: 组合 LED 闪烁和串口通信任务
 * 调度模式: auto (自动循环)
 *============================================================================*/

/**
 * @brief 系统初始化
 * @note  初始化所有外设模块
 */
void setup(void)
{
    led_blink_init();      // 初始化 LED 引脚
    uart_driver_init();    // 初始化串口
}

/**
 * @brief 主循环
 * @note  每 200ms 翻转一次 LED，每 2 秒发送一次 "HELLO"
 *        使用非阻塞方式管理时间间隔
 */
void loop(void)
{
    static unsigned long last_blink_time = 0;   // 上次 LED 翻转时间戳
    static unsigned long last_hello_time = 0;   // 上次串口发送时间戳
    const unsigned long blink_interval = 200;   // LED 闪烁间隔 (ms)
    const unsigned long hello_interval = 2000;  // 串口发送间隔 (ms)

    unsigned long current_time = millis();

    /* LED 闪烁任务：每 200ms 翻转一次 */
    if (current_time - last_blink_time >= blink_interval)
    {
        last_blink_time = current_time;
        led_blink_toggle();
    }

    /* 串口通信任务：每 2 秒发送一次 "HELLO" */
    if (current_time - last_hello_time >= hello_interval)
    {
        last_hello_time = current_time;
        uart_driver_send_hello();
    }
}