#include <Arduino.h>
/* FirmForge Boot Signature — AVR UART0 (TX=pin1, 9600) */
namespace {
struct _FirmForgeBoot {
    _FirmForgeBoot() {
        UBRR0H = (unsigned char)(103 >> 8);
        UBRR0L = (unsigned char)(103);
        UCSR0B = (1 << TXEN0);
        UCSR0C = (3 << UCSZ00);
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=c27b2f88\n";
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
#define LED_PIN         13          /* 板载 LED 引脚 (Arduino 引脚 13) */
#define LED_BLINK_MS    500         /* LED 闪烁间隔 (毫秒) */
#define SERIAL_BAUD     9600        /* 串口波特率 */

/*============================================================================
 * 模块: led_blink
 * 功能: 控制板载 LED 以 500ms 间隔闪烁
 * 依赖: 无
 *============================================================================*/

/**
 * @brief 初始化 LED 引脚为输出模式
 */
static void led_blink_init(void)
{
    pinMode(LED_PIN, OUTPUT);
    digitalWrite(LED_PIN, LOW);     /* 初始状态: 熄灭 */
}

/**
 * @brief 切换 LED 状态 (非阻塞)
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
 * 功能: 初始化串口并输出状态信息
 * 依赖: 无
 *============================================================================*/

/**
 * @brief 初始化 UART 串口 (9600 baud)
 */
static void uart_driver_init(void)
{
    Serial.begin(SERIAL_BAUD);
    /* 等待串口稳定 (Arduino 环境自动处理，此处仅作演示) */
    delay(100);
}

/**
 * @brief 通过串口输出 "OK" 状态信息
 */
static void uart_driver_report_ok(void)
{
    Serial.println("OK");
}

/*============================================================================
 * 主程序: setup() / loop()
 *============================================================================*/

/**
 * @brief Arduino 初始化函数，上电后执行一次
 */
void setup(void)
{
    /* 初始化各模块 */
    led_blink_init();
    uart_driver_init();

    /* 输出启动信息 */
    Serial.print("System started. LED blink every ");
    Serial.print(LED_BLINK_MS);
    Serial.println(" ms.");
}

/**
 * @brief Arduino 主循环，反复执行
 */
void loop(void)
{
    static unsigned long last_blink_time = 0;
    unsigned long current_time = millis();

    /* 非阻塞 LED 闪烁: 每 500ms 切换一次 */
    if (current_time - last_blink_time >= LED_BLINK_MS)
    {
        last_blink_time = current_time;
        led_blink_toggle();

        /* 每次切换 LED 时通过串口输出 "OK" */
        uart_driver_report_ok();
    }

    /* 其他任务可在此处添加，不会阻塞 LED 闪烁 */
}