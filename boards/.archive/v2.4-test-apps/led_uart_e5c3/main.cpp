#include <Arduino.h>
/* FirmForge Boot Signature — AVR UART0 (TX=pin1, 9600) */
namespace {
struct _FirmForgeBoot {
    _FirmForgeBoot() {
        UBRR0H = (unsigned char)(103 >> 8);
        UBRR0L = (unsigned char)(103);
        UCSR0B = (1 << TXEN0);
        UCSR0C = (3 << UCSZ00);
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=e5c32a05\n";
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
 * 引脚: LED_BUILTIN (Arduino引脚13)
 */

// LED闪烁间隔时间(毫秒)
#define LED_BLINK_INTERVAL_MS 200

/*
 * 初始化LED引脚为输出模式
 */
void led_blink_init(void)
{
    pinMode(LED_BUILTIN, OUTPUT);
    digitalWrite(LED_BUILTIN, LOW);
}

/*
 * 切换LED状态
 * 每次调用翻转LED电平
 */
void led_blink_toggle(void)
{
    static uint8_t led_state = LOW;
    led_state = (led_state == HIGH) ? LOW : HIGH;
    digitalWrite(LED_BUILTIN, led_state);
}

/*
 * uart_driver.c - UART通信模块
 * 功能: 通过串口发送"HELLO"字符串
 * 波特率: 9600
 * 引脚: TX=引脚1, RX=引脚0
 */

// 串口波特率
#define UART_BAUD_RATE 9600

// 发送消息内容
#define UART_MESSAGE "HELLO"

/*
 * 初始化UART串口
 */
void uart_driver_init(void)
{
    Serial.begin(UART_BAUD_RATE);
}

/*
 * 发送HELLO消息到串口
 */
void uart_driver_send_hello(void)
{
    Serial.println(UART_MESSAGE);
}

/*
 * main.c - 主程序
 * 功能: 组合LED闪烁和UART通信功能
 * 调度模式: auto (自动循环)
 */

void setup(void)
{
    // 初始化各功能模块
    led_blink_init();
    uart_driver_init();
}

void loop(void)
{
    // LED闪烁: 每200ms切换一次状态
    led_blink_toggle();
    
    // UART通信: 每次LED切换时发送HELLO消息
    uart_driver_send_hello();
    
    // 等待200ms
    delay(LED_BLINK_INTERVAL_MS);
}