#include <Arduino.h>
/* FirmForge Boot Signature — AVR UART0 (TX=pin1, 9600) */
namespace {
struct _FirmForgeBoot {
    _FirmForgeBoot() {
        UBRR0H = (unsigned char)(103 >> 8);
        UBRR0L = (unsigned char)(103);
        UCSR0B = (1 << TXEN0);
        UCSR0C = (3 << UCSZ00);
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=f058284a\n";
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

// LED闪烁周期常量（毫秒）
#define LED_BLINK_INTERVAL_MS 200

// 函数声明
void led_blink_init(void);
void led_blink_update(void);

// 模块内部状态
static unsigned long led_blink_last_toggle_ms = 0;
static uint8_t led_blink_state = LOW;

/*
 * 初始化LED引脚为输出模式
 */
void led_blink_init(void) {
    pinMode(LED_BUILTIN, OUTPUT);
    digitalWrite(LED_BUILTIN, LOW);
}

/*
 * 非阻塞LED闪烁更新
 * 每200ms切换一次LED状态
 */
void led_blink_update(void) {
    unsigned long current_ms = millis();
    if (current_ms - led_blink_last_toggle_ms >= LED_BLINK_INTERVAL_MS) {
        led_blink_last_toggle_ms = current_ms;
        led_blink_state = (led_blink_state == HIGH) ? LOW : HIGH;
        digitalWrite(LED_BUILTIN, led_blink_state);
    }
}

/*
 * uart_driver.c - UART通信模块
 * 功能: 通过串口以9600波特率发送"HELLO"消息
 * 引脚: TX=引脚1, RX=引脚0
 */

// 串口波特率常量
#define UART_BAUD_RATE 9600

// 消息发送间隔（毫秒）
#define UART_MESSAGE_INTERVAL_MS 1000

// 函数声明
void uart_driver_init(void);
void uart_driver_update(void);

// 模块内部状态
static unsigned long uart_last_send_ms = 0;

/*
 * 初始化UART串口通信
 * 波特率: 9600
 */
void uart_driver_init(void) {
    Serial.begin(UART_BAUD_RATE);
}

/*
 * 非阻塞串口消息发送
 * 每秒发送一次"HELLO"字符串
 */
void uart_driver_update(void) {
    unsigned long current_ms = millis();
    if (current_ms - uart_last_send_ms >= UART_MESSAGE_INTERVAL_MS) {
        uart_last_send_ms = current_ms;
        Serial.println("HELLO");
    }
}

/*
 * Arduino setup函数
 * 初始化所有功能模块
 */
void setup(void) {
    led_blink_init();
    uart_driver_init();
}

/*
 * Arduino loop函数
 * 循环执行所有功能模块的更新
 */
void loop(void) {
    led_blink_update();
    uart_driver_update();
}