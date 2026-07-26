# Layer 1 规则约束规范：编程范式选择与代码生成规则

> 日期：2026-07-12
> 依据：技术路线分析-LLM代码生成约束策略.md（分层混合路线 Layer 1）
> 状态：规范定义，待实现

---

## 一、编程范式定义（paradigm 枚举）

| paradigm | 典型 API | 抽象层级 | 适用 MCU |
|----------|---------|---------|---------|
| `arduino` | `pinMode` / `digitalWrite` / `Serial.begin` / `delay` | 最高 | AVR (Arduino 板) / ESP32 (Arduino 核心) |
| `hal` | `HAL_GPIO_WritePin` / `HAL_UART_Transmit` | 中高 | STM32 / GD32 (Cortex-M) |
| `ll` | `LL_GPIO_SetOutputPin` / `LL_USART_TransmitData8` | 中低 | STM32 (关键路径优化) |
| `register` | `DDRB` / `PORTB` / `GPIOA->BSRR` / `USART1->DR` | 最低 | AVR 裸片 / STM32 裸寄存器 |
| `esp_idf` | `gpio_set_level` / `uart_write_bytes` | 中 | ESP32 (ESP-IDF 原生) |

---

## 二、范式选择决策引擎（Init 阶段执行）

### 2.1 决策因子优先级

```
board_type (板子身份) → mcu_family (MCU 系列) → user_intent (用户意图关键词)
→ toolchain_availability (工具链可用性) → board.json override (用户显式指定)
```

### 2.2 决策规则表

| # | board_type | mcu_family | 用户意图关键词 | 工具链 | → paradigm |
|---|-----------|-----------|--------------|--------|-----------|
| R1 | Arduino 板 (Uno/Mega/Nano) | AVR | — | avr-gcc + Arduino Core | `arduino` |
| R2 | Arduino 板 | AVR | "寄存器/底层/裸机" | avr-gcc | `register` |
| R3 | 裸 MCU 板 | AVR | — | avr-gcc (无 Arduino Core) | `register` |
| R4 | — | STM32 (Cortex-M) | "生产/产品/CubeMX" | arm-gcc + HAL | `hal` |
| R5 | — | STM32 | "实时/电机/低延迟" | arm-gcc + LL | `ll` |
| R6 | — | STM32 | "学习寄存器/裸机" | arm-gcc | `register` |
| R7 | — | STM32 | — | arm-gcc (无 HAL) | `register` |
| R8 | ESP32 开发板 | ESP32 | "Arduino/快速原型" | esp-arduino-core | `arduino` |
| R9 | ESP32 开发板 | ESP32 | "ESP-IDF/FreeRTOS" | esp-idf | `esp_idf` |
| R10 | 任何 | 任何 | 用户在 board.json 显式指定 `paradigm` | — | 用户指定值（最高优先级） |

### 2.3 用户意图关键词映射

| 关键词（中文/英文） | 倾向范式 |
|---|---|
| 快速原型 / 教学 / 示例 / demo / quick / prototype | `arduino` |
| 生产 / 产品 / 工业 / CubeMX / production / industrial | `hal` |
| 实时 / 电机 / 低延迟 / real-time / motor / low-latency | `ll` |
| 学习寄存器 / 底层 / 裸机 / 极致优化 / register / bare-metal | `register` |
| ESP-IDF / FreeRTOS / WiFi / 蓝牙 / esp-idf | `esp_idf` |

### 2.4 board.json schema 扩展

```json
{
  "board_id": "arduino_mega",
  "platform": "arduino",
  "mcu": { "chip": "ATmega2560", "series": "avr", "family": "avr" },
  "board_type": "arduino_board",         // "arduino_board" | "bare_mcu" | "dev_board"
  "paradigm": "arduino",                  // 显式指定（最高优先级），或留空由引擎推断
  "paradigm_locked": false,               // true=禁止用户意图覆盖（安全关键场景）
  "toolchain": {
    "core_available": true,              // Arduino Core / HAL / ESP-IDF 是否可链接
    "core_path": "~/.firmforge/toolchains/arduino-avr-core"
  }
}
```

### 2.5 范式推断算法（伪代码）

```python
def infer_paradigm(board_config, user_intent, toolchain_info):
    # 0. 用户显式指定 → 直接返回
    if board_config.get("paradigm"):
        return board_config["paradigm"]

    # 1. 板子身份
    board_type = board_config.get("board_type", "bare_mcu")
    mcu_family = board_config.get("mcu", {}).get("family", "")

    # 2. 用户意图关键词匹配
    intent_lower = user_intent.lower()
    if any(k in intent_lower for k in ["寄存器", "底层", "裸机", "register", "bare-metal"]):
        return "register"
    if any(k in intent_lower for k in ["生产", "产品", "cube", "production", "industrial"]):
        if mcu_family in ("stm32", "gd32"):
            return "hal"
    if any(k in intent_lower for k in ["实时", "电机", "real-time", "motor"]):
        if mcu_family in ("stm32", "gd32"):
            return "ll"
    if any(k in intent_lower for k in ["esp-idf", "freertos", "wifi", "蓝牙"]):
        if mcu_family == "esp32":
            return "esp_idf"
    if any(k in intent_lower for k in ["快速", "原型", "教学", "示例", "demo", "prototype"]):
        if board_type == "arduino_board":
            return "arduino"

    # 3. 板子身份 + MCU 系列默认
    if board_type == "arduino_board":
        return "arduino" if toolchain_info.get("core_available") else "register"

    # 裸 MCU 板
    if mcu_family == "avr":
        return "register"
    if mcu_family in ("stm32", "gd32"):
        return "hal" if toolchain_info.get("core_available") else "register"
    if mcu_family == "esp32":
        return "esp_idf" if toolchain_info.get("core_available") else "register"

    # 兜底
    return "register"
```

---

## 三、各范式下的 LLM 代码生成规则

### 3.1 paradigm = `arduino`

**Prompt 注入规则**：
```
你必须使用 Arduino 核心 API 编写代码：
- GPIO: pinMode(pin, mode) / digitalWrite(pin, val) / digitalRead(pin)
- 串口: Serial.begin(baud) / Serial.print(str) / Serial.println(str)
- 延时: delay(ms) / delayMicroseconds(us)
- 模拟: analogRead(pin) / analogWrite(pin, val)
- 结构: setup() + loop() 函数
- 禁止: 直接操作 DDRB/PORTB/UCSR0B 等寄存器
- 头文件: #include <Arduino.h>
```

**Citation Gate 行为**：校验 API 函数名在 api.json 中存在；寄存器引用视为 warning（不阻断）。

### 3.2 paradigm = `hal`

**Prompt 注入规则**：
```
你必须使用 STM32 HAL 库编写代码：
- GPIO: HAL_GPIO_WritePin(port, pin, state) / HAL_GPIO_ReadPin
- UART: HAL_UART_Transmit(huart, data, len, timeout)
- 初始化: MX_GPIO_Init() / MX_USART1_UART_Init() 风格
- 结构: main() 函数 + while(1) 循环
- 禁止: 直接操作 GPIOA->BSRR / USART1->DR 等寄存器
- 头文件: #include "stm32f1xx_hal.h"
```

### 3.3 paradigm = `ll`

**Prompt 注入规则**：
```
你必须使用 STM32 LL 库编写代码：
- GPIO: LL_GPIO_SetOutputPin(port, mask) / LL_GPIO_ResetOutputPin
- UART: LL_USART_TransmitData8(usart, data)
- 禁止: 使用 HAL_* 函数
- 禁止: 直接寄存器操作（除非 LL 库无对应功能）
- 头文件: #include "stm32f1xx_ll.h"
```

### 3.4 paradigm = `register`

**Prompt 注入规则**：
```
你必须使用直接寄存器操作编写代码：
- AVR: DDRB/PORTB/PINB/UCSR0A/UDR0/UBRR0L 等寄存器
- STM32: GPIOA->BSRR / USART1->DR / RCC->APB2ENR 等寄存器
- 位操作: (1 << bit) / |= / &= ~
- 禁止: 调用 pinMode/digitalWrite/HAL_* 等封装函数
- 头文件: #include <avr/io.h> (AVR) 或 #include "stm32f1xx.h" (STM32)
- 结构: main() 函数 + while(1) 循环
```

**Citation Gate 行为**：强制校验每个寄存器名在 reference 库中存在；未索引的寄存器 → error 阻断。

### 3.5 paradigm = `esp_idf`

**Prompt 注入规则**：
```
你必须使用 ESP-IDF API 编写代码：
- GPIO: gpio_set_level(pin, level) / gpio_config(cfg)
- UART: uart_write_bytes(port, data, len)
- 结构: app_main() 函数 + FreeRTOS 任务
- 禁止: 直接寄存器操作
- 头文件: #include "driver/gpio.h" / #include "freertos/FreeRTOS.h"
```

### 3.6 混合模式规则

**允许的混合**：初始化用 HAL + 关键路径用 LL/寄存器

**board.json 声明**：
```json
{
  "paradigm": "hal",
  "mixed_allow": ["ll", "register"]
}
```

**Prompt 注入**：
```
主范式: HAL 库（初始化、常规外设）
允许混合: 关键路径（时序敏感）可用 LL 库或寄存器操作
混合规则: 同一函数内禁止跨范式混调；使用 LL/寄存器的函数需注释说明原因
```

**Citation Gate 行为**：HAL 和 LL 函数都校验；寄存器引用按 paradigm=`register` 规则校验。

---

## 四、Init 阶段范式推断流程

```
用户输入 → ff run arduino_mega "led闪烁+串口心跳"
                │
                ▼
┌─────────────────────────────────┐
│ Init 阶段                       │
│ 1. USB 扫描 → board_id          │
│ 2. 加载 board.json              │
│ 3. 检测工具链可用性              │
│    (Arduino Core / HAL / IDF)   │
│ 4. 范式推断引擎                  │
│    board_type = arduino_board   │
│    mcu_family = avr             │
│    user_intent = "led闪烁+串口"  │
│    core_available = true        │
│    → paradigm = "arduino"       │
│ 5. 将 paradigm 注入 plan.md     │
└─────────────────────────────────┘
                │
                ▼
┌─────────────────────────────────┐
│ Code 阶段                       │
│ CodeGenerator 读 paradigm       │
│ → 加载对应范式 prompt 规则       │
│ → 生成 Arduino API 风格代码      │
│ → pinMode/digitalWrite/Serial   │
└─────────────────────────────────┘
                │
                ▼
┌─────────────────────────────────┐
│ Citation Gate                   │
│ paradigm=arduino → 校验 API 名  │
│ paradigm=register → 校验寄存器名│
└─────────────────────────────────┘
```

---

## 五、实施清单

1. board.json 加 `paradigm` / `board_type` / `paradigm_locked` / `mixed_allow` / `toolchain` 字段
2. 创建 `firmforge/core/paradigm_resolver.py`：范式推断引擎
3. CodeGenerator.build_prompt() 根据 paradigm 选择不同的 prompt 模板
4. PlanSpec 加 `paradigm` 字段，Plan 生成时写入
5. ToolOrchestrator._stage_init() 调用 paradigm_resolver
6. Citation Gate 行为根据 paradigm 调整（arduino=API校验/register=寄存器校验）
7. 测试覆盖所有范式推断规则
