#include <Arduino.h>
/* FirmForge Boot Signature — AVR UART0 (TX=pin1, 9600) */
namespace {
struct _FirmForgeBoot {
    _FirmForgeBoot() {
        UBRR0H = (unsigned char)(103 >> 8);
        UBRR0L = (unsigned char)(103);
        UCSR0B = (1 << TXEN0);
        UCSR0C = (3 << UCSZ00);
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=f6caca5c\n";
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
#define BLINK_INTERVAL_MS 200          /* LED 闪烁间隔 (毫秒) */
#define HELLO_INTERVAL_MS 2000         /* 串口打印间隔 (毫秒) */

/*============================================================================
 * 模块函数声明
 *============================================================================*/

/**
 * @brief LED 闪烁模块 - 切换 LED 状态
 * 依赖: 无
 */
void led_blink_toggle(void);

/**
 * @brief UART 通信模块 - 发送 "HELLO" 字符串
 * 依赖: 无
 */
void uart_send_hello(void);

/*============================================================================
 * 模块函数实现
 *============================================================================*/

/**
 * @brief 切换板载 LED 的亮灭状态
 * 
 * 该函数读取当前 LED 引脚电平并取反，实现闪烁效果。
 * 调用前需确保 LED 引脚已配置为 OUTPUT。
 */
void led_blink_toggle(void)
{
    /* 读取当前 LED 状态并取反 */
    uint8_t current_state = digitalRead(LED_PIN);
    digitalWrite(LED_PIN, (current_state == HIGH) ? LOW : HIGH);
}

/**
 * @brief 通过串口发送 "HELLO" 字符串并换行
 * 
 * 该函数使用 Serial.println() 发送预定义的问候消息。
 * 调用前需确保串口已初始化 (Serial.begin())。
 */
void uart_send_hello(void)
{
    Serial.println("HELLO");
}

/*============================================================================
 * Arduino 核心函数
 *============================================================================*/

/**
 * @brief 初始化函数，在系统启动时执行一次
 * 
 * 配置 LED 引脚为输出，初始化串口通信。
 */
void setup(void)
{
    /* 配置板载 LED 引脚为输出模式 */
    pinMode(LED_PIN, OUTPUT);
    /* 初始状态：LED 熄灭 */
    digitalWrite(LED_PIN, LOW);

    /* 初始化串口通信，波特率 9600 */
    Serial.begin(SERIAL_BAUD);

    /* 等待串口稳定（可选，用于某些 USB 转串口适配器） */
    delay(100);
}

/**
 * @brief 主循环函数，重复执行
 * 
 * 实现两个周期性任务：
 * 1. LED 闪烁：每 200ms 切换一次状态
 * 2. 串口发送：每 2000ms 发送一次 "HELLO"
 * 
 * 使用非阻塞方式（基于 millis() 时间戳）实现多任务调度。
 */
void loop(void)
{
    /* 静态变量保存上次执行时间（毫秒） */
    static unsigned long last_blink_time = 0;
    static unsigned long last_hello_time = 0;

    unsigned long current_time = millis();

    /* ---- 任务 1: LED 闪烁 (每 200ms) ---- */
    if (current_time - last_blink_time >= BLINK_INTERVAL_MS)
    {
        last_blink_time = current_time;
        led_blink_toggle();
    }

    /* ---- 任务 2: 串口发送 "HELLO" (每 2000ms) ---- */
    if (current_time - last_hello_time >= HELLO_INTERVAL_MS)
    {
        last_hello_time = current_time;
        uart_send_hello();
    }
}