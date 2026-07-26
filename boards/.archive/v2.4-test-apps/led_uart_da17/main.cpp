#include <Arduino.h>
/* FirmForge Boot Signature — AVR UART0 (TX=pin1, 9600) */
namespace {
struct _FirmForgeBoot {
    _FirmForgeBoot() {
        UBRR0H = (unsigned char)(103 >> 8);
        UBRR0L = (unsigned char)(103);
        UCSR0B = (1 << TXEN0);
        UCSR0C = (3 << UCSZ00);
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=da17e539\n";
        for (const char* p = sig; *p; p++) {
            while (!(UCSR0A & (1 << UDRE0))) { }
            UDR0 = (unsigned char)(*p);
        }
    }
} _firmforge_boot;
}

/*
 * led_blink.c - LED闪烁模块
 * 功能: 控制板载LED以200ms间隔闪烁
 * 引脚: LED_BUILTIN (引脚13)
 */

// LED闪烁间隔时间（毫秒）
#define LED_BLINK_INTERVAL_MS 200

/*
 * 初始化LED引脚
 * 将板载LED引脚设置为输出模式
 */
void led_blink_init(void)
{
    pinMode(LED_BUILTIN, OUTPUT);
    digitalWrite(LED_BUILTIN, LOW);
}

/*
 * 更新LED状态
 * 切换LED引脚电平，实现闪烁效果
 */
void led_blink_update(void)
{
    static uint8_t led_state = LOW;
    
    led_state = (led_state == HIGH) ? LOW : HIGH;
    digitalWrite(LED_BUILTIN, led_state);
}

/*
 * uart_driver.c - UART通信模块
 * 功能: 通过串口发送"HELLO"字符串
 * 引脚: TX=引脚1, RX=引脚0
 * 波特率: 9600
 */

// 串口通信波特率
#define UART_BAUD_RATE 9600

// 发送消息内容
#define UART_MESSAGE "HELLO"

/*
 * 初始化UART模块
 * 配置串口通信参数
 */
void uart_driver_init(void)
{
    Serial.begin(UART_BAUD_RATE);
}

/*
 * 发送HELLO消息
 * 通过串口输出预定义字符串
 */
void uart_driver_send_hello(void)
{
    Serial.println(UART_MESSAGE);
}

/*
 * 主程序入口
 * Arduino标准结构：setup() + loop()
 */

void setup(void)
{
    // 初始化所有功能模块
    led_blink_init();
    uart_driver_init();
}

void loop(void)
{
    // 更新LED闪烁状态
    led_blink_update();
    
    // 发送HELLO消息
    uart_driver_send_hello();
    
    // 等待200ms后继续
    delay(LED_BLINK_INTERVAL_MS);
}