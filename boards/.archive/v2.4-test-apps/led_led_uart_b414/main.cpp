/**
 * FirmForge - Heartbeat Cycle
 * Board: Arduino Mega 2560 (ATmega2560)
 *
 * 功能: LED 以 1s / 3s / 5s 三档周期循环闪烁
 *       每次心跳串口输出编号 + ASCII 字符画 + 对应 ASCII 码
 */

#include <Arduino.h>

/* ---- 常量 ---- */
#define LED_PIN          LED_BUILTIN       /* Pin 13 */
#define SERIAL_BAUD      9600              /* 串口波特率 */
#define CYCLE_COUNT      3                 /* 闪烁周期档数 */

/* 三档闪烁周期 (ms): 1s, 3s, 5s */
const unsigned long BLINK_PERIODS[CYCLE_COUNT] = {1000, 3000, 5000};

/* ---- 全局状态 ---- */
static uint8_t      cycle_index   = 0;     /* 当前周期档位 0/1/2 */
static unsigned long heartbeat_num = 0;     /* 心跳累计编号   */

/* ---- 函数声明 ---- */
static void print_header(void);
static void print_ascii_heart(void);
static void print_heartbeat_info(unsigned long num, unsigned long period_ms);

/* ================================================================
 *  setup() — 初始化
 * ================================================================ */
void setup(void) {
    pinMode(LED_PIN, OUTPUT);
    digitalWrite(LED_PIN, LOW);

    Serial.begin(SERIAL_BAUD);
    delay(500);  /* 等待串口稳定 */

    print_header();
}

/* ================================================================
 *  loop() — 主循环：周期性闪烁 + 串口输出
 * ================================================================ */
void loop(void) {
    unsigned long period = BLINK_PERIODS[cycle_index];
    heartbeat_num++;

    /* ---- 点亮 LED ---- */
    digitalWrite(LED_PIN, HIGH);

    /* ---- 串口输出心跳信息 ---- */
    print_heartbeat_info(heartbeat_num, period);

    /* ---- 输出 ASCII 字符画 ---- */
    print_ascii_heart();

    /* ---- 输出对应的 ASCII 码 ---- */
    Serial.print("  >> ASCII Code: 0x");
    Serial.print(heartbeat_num, HEX);
    Serial.print(" (DEC: ");
    Serial.print(heartbeat_num);
    Serial.print(")");

    if (heartbeat_num >= 0x20 && heartbeat_num <= 0x7E) {
        /* 可打印 ASCII 字符直接输出 */
        Serial.print(" -> '");
        Serial.write((uint8_t)heartbeat_num);
        Serial.print("'");
    } else if (heartbeat_num < 0x20) {
        Serial.print(" [Control Char]");
    } else if (heartbeat_num == 0x7F) {
        Serial.print(" [DEL]");
    } else {
        Serial.print(" [Extended]");
    }
    Serial.println();

    Serial.println("==============================================");
    Serial.flush();

    /* ---- 保持亮灯半周期 ---- */
    delay(period / 2);

    /* ---- 熄灭 LED ---- */
    digitalWrite(LED_PIN, LOW);

    /* ---- 保持灭灯半周期 ---- */
    delay(period / 2);

    /* ---- 切换到下一档周期 (1s → 3s → 5s → 1s ...) ---- */
    cycle_index = (cycle_index + 1) % CYCLE_COUNT;
}

/* ================================================================
 *  print_header() — 启动横幅
 * ================================================================ */
static void print_header(void) {
    Serial.println();
    Serial.println("+==========================================+");
    Serial.println("|   FirmForge Heartbeat Cycle v1.0         |");
    Serial.println("|   Board: Arduino Mega 2560               |");
    Serial.println("|   Cycle: 1s / 3s / 5s                   |");
    Serial.println("+==========================================+");
    Serial.println();
}

/* ================================================================
 *  print_ascii_heart() — 打印 ASCII 爱心字符画
 * ================================================================ */
static void print_ascii_heart(void) {
    Serial.println();
    Serial.println("       *********       *********");
    Serial.println("    **************   **************");
    Serial.println("  ***************** *****************");
    Serial.println(" *************************************");
    Serial.println("  ********************************** ");
    Serial.println("   *******************************  ");
    Serial.println("    ****************************   ");
    Serial.println("      ************************     ");
    Serial.println("        ********************       ");
    Serial.println("          ****************         ");
    Serial.println("            ************           ");
    Serial.println("              ********             ");
    Serial.println("                ****               ");
    Serial.println("                 **                ");
    Serial.println();
}

/* ================================================================
 *  print_heartbeat_info() — 打印心跳编号 & 周期信息
 * ================================================================ */
static void print_heartbeat_info(unsigned long num, unsigned long period_ms) {
    Serial.println("==============================================");
    Serial.print("  Heartbeat #");
    Serial.print(num);
    Serial.print("  |  Period: ");
    Serial.print(period_ms / 1000.0f, 1);
    Serial.println("s");
}
