#include <Arduino.h>
/* FirmForge Boot Signature — AVR UART0 (TX=pin1, 9600) */
namespace {
struct _FirmForgeBoot {
    _FirmForgeBoot() {
        UBRR0H = (unsigned char)(103 >> 8);
        UBRR0L = (unsigned char)(103);
        UCSR0B = (1 << TXEN0);
        UCSR0C = (3 << UCSZ00);
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=f5630911\n";
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

// LED闪烁间隔时间（毫秒）
#define LED_BLINK_INTERVAL_MS 200

// LED状态变量
static bool led_state = LOW;

/**
 * 初始化LED引脚
 */
void led_blink_init(void)
{
    pinMode(LED_BUILTIN, OUTPUT);
    digitalWrite(LED_BUILTIN, LOW);
}

/**
 * 更新LED状态 - 切换电平
 */
void led_blink_update(void)
{
    led_state = !led_state;
    digitalWrite(LED_BUILTIN, led_state);
}

/*
 * uart_driver.c - UART通信模块
 * 功能: 通过串口发送"HELLO"字符串
 * 波特率: 9600
 * 引脚: TX=引脚1, RX=引脚0
 */

// 串口波特率
#define UART_BAUDRATE 9600

// 发送的消息
#define UART_MESSAGE "HELLO"

// 消息发送间隔（毫秒）
#define UART_SEND_INTERVAL_MS 1000

// 上次发送时间戳
static unsigned long last_uart_send_time = 0;

/**
 * 初始化UART串口
 */
void uart_driver_init(void)
{
    Serial.begin(UART_BAUDRATE);
}

/**
 * 发送HELLO消息（非阻塞方式）
 */
void uart_driver_send_hello(void)
{
    unsigned long current_time = millis();
    
    // 检查是否到达发送间隔
    if (current_time - last_uart_send_time >= UART_SEND_INTERVAL_MS)
    {
        last_uart_send_time = current_time;
        Serial.println(UART_MESSAGE);
    }
}

/*
 * main.c - 主程序
 * 功能: 整合LED闪烁和UART通信模块
 * 调度模式: auto (自动循环)
 */

void setup(void)
{
    // 初始化各模块
    led_blink_init();
    uart_driver_init();
}

void loop(void)
{
    // 更新LED闪烁（200ms间隔）
    led_blink_update();
    delay(LED_BLINK_INTERVAL_MS);
    
    // 发送HELLO消息（1秒间隔）
    uart_driver_send_hello();
}