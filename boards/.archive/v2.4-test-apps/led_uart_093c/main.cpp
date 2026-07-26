#include <Arduino.h>
/* FirmForge Boot Signature — AVR UART0 (TX=pin1, 9600) */
namespace {
struct _FirmForgeBoot {
    _FirmForgeBoot() {
        UBRR0H = (unsigned char)(103 >> 8);
        UBRR0L = (unsigned char)(103);
        UCSR0B = (1 << TXEN0);
        UCSR0C = (3 << UCSZ00);
        const char* sig = "FIRMFORGE:board=arduino_uno chip=atmega328p F_CPU=16000000 build=093c465d\n";
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
#define LED_PIN         13          /* 板载 LED 引脚 (PB7) */
#define SERIAL_BAUD     9600UL      /* 串口波特率 */
#define BLINK_INTERVAL  500         /* LED 闪烁间隔 (毫秒) */

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
 * @brief 切换 LED 状态
 */
static void led_blink_toggle(void)
{
    static uint8_t led_state = LOW;
    led_state = (led_state == LOW) ? HIGH : LOW;
    digitalWrite(LED_PIN, led_state);
}

/*============================================================================
 * 模块: uart_driver
 * 功能: 通过串口输出计数信息 (9600 baud)
 * 依赖: 无
 *============================================================================*/

/**
 * @brief 初始化串口通信
 */
static void uart_driver_init(void)
{
    Serial.begin(SERIAL_BAUD);
    while (!Serial) {               /* 等待串口就绪 (仅对原生USB有效) */
        delay(10);
    }
    Serial.println(F("UART initialized at 9600 baud"));
}

/**
 * @brief 发送当前计数值到串口
 * @param count  当前计数值
 */
static void uart_driver_print_count(uint32_t count)
{
    Serial.print(F("COUNT: "));
    Serial.println(count);
}

/*============================================================================
 * 主程序
 *============================================================================*/

static uint32_t blink_counter = 0;  /* 闪烁次数计数器 */

void setup(void)
{
    led_blink_init();               /* 初始化 LED */
    uart_driver_init();             /* 初始化串口 */
}

void loop(void)
{
    /* 每 500ms 切换一次 LED 并输出计数 */
    led_blink_toggle();
    blink_counter++;
    uart_driver_print_count(blink_counter);
    delay(BLINK_INTERVAL);
}