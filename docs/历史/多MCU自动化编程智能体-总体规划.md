# 多MCU自动化编程智能体 — 总体规划

> 版本：v1.0 | 日期：2026-07-06 | 状态：设计阶段
>
> 目标芯片：STC8H8K64U（阶段 0-4） → STM32F103 / Arduino Mega2560（后续扩展）
>
> 架构方案：松耦合通用架构（核心 Python 包 + 薄适配器），Codebuddy 通过 MCP Server 接入

---

## 产品概述

设计面向 **STC8H8K64U / STM32F103 / Arduino Mega2560** 多系列 MCU 的端到端自动化硬件编程智能体——一个符合业界标准的领域专用 Agent。用户以自然语言描述需求，智能体自动完成代码生成、编译、烧录、硬件在环测试与验证的完整闭环。

采用 **"核心库 + 薄适配器"松耦合通用架构**，各层级高内聚、低耦合、易扩展。核心逻辑独立于任何 AI IDE 平台，通过 MCP Server 接入 Codebuddy，CLI 独立可用。代码层遵循 `apps → A-HAL → vendor → 寄存器` 调用链，**AI Agent 绝不越过 A-HAL 直接操作寄存器**。

## 核心功能

- **自然语言驱动全链路**：一句话描述需求（如"让 PA0 引脚每 500ms 翻转一次"），自动编码→编译→烧录→串口验证，输出 PASS/FAIL
- **A-HAL 硬件抽象层**：基于厂商库函数之上的 Agent 业务功能函数层，AI Agent 只调用 A-HAL，屏蔽寄存器直接操作
- **多 MCU 统一抽象**：通过 BuildProvider / FlashProvider / TestProvider 接口屏蔽芯片差异，新增 MCU 只需实现适配器
- **数据手册 RAG + 代码知识库**：统一的记忆/知识层，融合芯片手册知识 + A-HAL API 知识 + 历史任务经验
- **HIL 硬件在环测试**：单片机端轻量 assert 宏 + 主机端自动串口收集判定
- **Agent Tracing 可观测性**：任务全链路追踪（plan→generate→compile→flash→hil_test→verdict），记录每步耗时与结果
- **Benchmark 评测体系**：标准化测试用例集，量化编译通过率、端到端成功率、代码正确率
- **Embedded Skills 体系**：可复用的驱动代码生成技能（GPIO/UART/ADC/Timer 等）
- **多平台接入**：核心 Python 包 + MCP Server（Codebuddy）+ CLI，预留 VS Code 扩展接口

## 技术选型

| 维度 | 选型 | 理由 |
| --- | --- | --- |
| 核心语言 | Python 3.10+ | pyserial/stcgal 生态，MCP 协议原生 |
| 编译器(STC8H) | SDCC 4.5.0 | 开源免费，本机已有 |
| 编译器(STM32) | ARM GCC | 免费，工业级，CMSIS 支持 |
| 编译器(Arduino) | AVR-GCC / Arduino CLI | 官方支持 |
| 烧录(STC8H) | stcgal | 开源，UART ISP，自动 DTR |
| 烧录(STM32) | OpenOCD / pyOCD | 标准 SWD，Python 原生 |
| 烧录(Arduino) | avrdude / Arduino CLI | 官方工具链 |
| 测试框架 | assert宏 + pyserial + pytest | 轻量嵌入式，Python 生态 |
| RAG引擎 | ChromaDB + Embedding | 本地离线，手册 + A-HAL 知识向量化 |
| MCP协议 | stdio(本地) + SSE(远程) | Codebuddy 标准协议 |
| Tracing | JSONL 本地文件 | 轻量，无需外部依赖 |

## 架构设计

```
┌──────────────────────────────────────────────────┐
│  交互适配层 (Adapters)                            │
│  CLI | MCP Server (Codebuddy) | VS Code Ext       │
├──────────────────────────────────────────────────┤
│  智能体核心层 (Agent Core)                        │
│  TaskPlanner → CodeGenerator → ToolOrchestrator   │
├──────────────────────────────────────────────────┤
│  记忆/知识层 (Memory & Knowledge)                 │
│  RAG Service (手册+A-HAL) | Agent Trace | Benchmark│
├──────────────────────────────────────────────────┤
│  公共设施层 (Facilities)                          │
│  HIL Framework | Skills Repo | Tracing Logger     │
├──────────────────────────────────────────────────┤
│  MCU 提供者层 (Providers)                         │
│  BuildProvider | FlashProvider | TestProvider     │
├──────────────────────────────────────────────────┤
│  代码层 (Code)                                    │
│  apps/       ← AI 生成层（只调 A-HAL）            │
│  ahal/       ← A-HAL 层（业务功能函数，每个MCU专属）│
│  vendor/     ← 官方库函数（只读基础）              │
└──────────────────────────────────────────────────┘
```

### 调用链约束（核心原则）

```
apps/ ──→ ahal/stc8h8k64u/ ──→ vendor/stc8h/ ──→ 寄存器
        NEVER skip ahal!      (厂商库函数)

apps/ ──→ ahal/stm32f103/ ──→ vendor/stm32/ ──→ HAL/CMSIS ──→ 寄存器

apps/ ──→ ahal/arduino_mega/ ──→ vendor/arduino/ ──→ AVR 寄存器
```

AI Agent 生成的所有代码只调用 A-HAL 层接口，绝不直接操作寄存器。

### A-HAL 层定义

**A-HAL** = Agent Hardware Abstraction Layer（面向 AI Agent 的硬件抽象层）

- **职责**：在厂商库函数基础上封装面向业务的功能函数，提供统一、语义化的编程接口
- **每个 MCU 专属目录**：`ahal/stc8h8k64u/` / `ahal/stm32f103/` / `ahal/arduino_mega/`
- **配套代码知识库**：`knowledge/<chip>/ahal_api.json` 记录所有 A-HAL API 签名与使用模式，供 RAG 吸收

示例 A-HAL 接口风格：

```c
// ahal/stc8h8k64u/gpio.h —— 语义化的 AI 友好接口
void ahal_gpio_set_mode(uint8_t pin, uint8_t mode);   // INPUT/OUTPUT/...
void ahal_gpio_write(uint8_t pin, uint8_t value);      // HIGH/LOW
uint8_t ahal_gpio_read(uint8_t pin);

void ahal_delay_ms(uint16_t ms);                       // 毫秒延时
void ahal_uart_init(uint8_t uart_id, uint32_t baud);  // 串口初始化
void ahal_uart_send(uint8_t uart_id, const char* data);
```

### 记忆/知识层设计

该层统一管理 Agent 的"记忆"和"知识"，供 RAG 检索消费：

```
memory/ (可向量化持久化)
├── datasheets/           # 数据手册知识（芯片寄存器、外设参数）
│   ├── stc8h8k64u/       # 从 STC 官方 MCP 拉取 + 缓存
│   ├── stm32f103/        # [后续] STM32 HAL 参考手册
│   └── arduino_mega/     # [后续] ATmega2560 数据手册
├── ahal_knowledge/       # 代码知识库（A-HAL API + 使用模式）
│   ├── stc8h8k64u/
│   │   ├── ahal_api.json          # A-HAL 函数签名、参数、返回值
│   │   ├── usage_examples/        # 常见任务示例代码
│   │   └── patterns/              # 常见任务模式（点灯/串口/ADC...）
│   ├── stm32f103/                 # [后续]
│   └── arduino_mega/              # [后续]
└── agent_traces/         # Agent 运行追踪（历史任务记录）
    └── 2026-07-05/001.jsonl
```

RAG Service 启动时将这些知识全部向量化存入 ChromaDB，Agent 代码生成时一次检索即可命中"手册定义 + A-HAL 用法 + 历史成功模式"。

### 核心接口契约

```python
class BuildProvider(Protocol):
    def compile(self, source_dir: Path, target: str) -> BuildResult:
        """编译源代码，返回 .hex/.bin 路径 + 编译日志"""
        ...

class FlashProvider(Protocol):
    def detect_port(self) -> str:
        """自动检测目标芯片连接的串口/SWD"""
        ...
    def flash(self, firmware: Path, port: str) -> FlashResult:
        """烧录固件，返回成功/失败"""
        ...

class TestProvider(Protocol):
    def monitor(self, port: str, timeout: float) -> TestReport:
        """监听串口输出，收集 assert 结果，返回 PASS/FAIL 报告"""
        ...
```

### 数据流

```
用户自然语言
  ↓
TaskPlanner 解析意图 → 确定 MCU + 外设类型
  ↓
CodeGenerator ← RAG(手册 + A-HAL 知识) 检索最佳匹配
  ↓
生成 apps/ 代码（只调 ahal/ 接口）
  ↓
BuildProvider.compile() → 编译 .hex
  ↓
FlashProvider.flash() → 烧录
  ↓
TestProvider.monitor() → 串口收集 assert 结果
  ↓
Tracing 记录全链路日志
  ↓
输出 PASS/FAIL + 评测指标
```

### 关键决策

1. **SDCC 为主线**（无 Keil 授权），需自建 STC8H SDCC BSP 头文件（SFR 定义、中断向量适配）
2. **先 CLI 验证闭环**，再封装 MCP Server 接入 Codebuddy
3. **AI 绝不直接操作寄存器**：所有生成代码必须通过 A-HAL 层调用，A-HAL 再调用 vendor 库函数
4. **RAG 本地优先**：ChromaDB 向量缓存手册 + A-HAL 知识，miss 时降级请求远程 MCP
5. **记忆层吸收代码知识库**：A-HAL API 文档和模式统一纳入 RAG，一次检索出全部上下文
6. **HIL 三层**：单片机 ASSERT 宏 → 主机 HILCollector → HILReporter

## 初始阶段公共设施清单

| # | 设施 | 说明 | 优先级 |
|---|------|------|--------|
| 1 | **数据手册 RAG 服务** | ChromaDB 向量存储 + 远程 MCP 降级查询 | P0 |
| 2 | **A-HAL 代码知识库** | 每个 MCU 的 A-HAL API 定义 + 使用示例 + 常见模式 | P0 |
| 3 | **HIL 硬件在环框架** | MCU 端 assert 宏 + PC 端串口收集 + 报告生成 | P0 |
| 4 | **Agent Tracing** | JSONL 任务链路追踪（plan→gen→build→flash→test→verdict） | P1 |
| 5 | **Embedded Skills 仓库** | 驱动代码模板（GPIO/UART/Timer/ADC…），按外设类型匹配 | P1 |
| 6 | **Benchmark 评测套件** | 标准化测试用例 + 端到端成功率统计 | P1 |
| 7 | **SDCC BSP 头文件** | STC8H8K64U SFR 定义、中断向量、__at 宏适配 | P0 |

## 目录结构

```
MCU/
├── docs/
│   └── 多MCU自动化编程智能体-总体规划.md
├── mcu_agent/                          # [NEW] 核心 Python 包
│   ├── core/                           # 平台无关 Agent 核心
│   │   ├── task_planner.py             # 自然语言意图解析
│   │   ├── code_generator.py           # 代码生成引擎（RAG驱动）
│   │   ├── tool_orchestrator.py        # 工具编排器
│   │   ├── knowledge_base.py           # RAG 知识库管理
│   │   └── tracer.py                   # Agent 运行追踪
│   ├── providers/                      # MCU 适配器（Provider 接口实现）
│   │   ├── base.py                     # BuildProvider/FlashProvider/TestProvider 协议
│   │   ├── stc8h/                      # STC8H8K64U (SDCC+stcgal)
│   │   │   ├── build.py                # SDCC Makefile 生成 + 编译
│   │   │   ├── flash.py                # stcgal 封装
│   │   │   └── test.py                 # 串口监视 + assert 收集
│   │   ├── stm32f103/                  # [后续] STM32F103 (ARM GCC+OpenOCD)
│   │   └── arduino_mega/               # [后续] Arduino Mega (AVR-GCC+avrdude)
│   ├── facilities/                     # 公共设施
│   │   ├── rag_service.py              # 数据手册 + A-HAL 知识 RAG
│   │   ├── hil_framework.py            # HIL 框架
│   │   └── skills_repo.py              # Embedded Skills 仓库
│   └── adapters/                       # 平台适配器（薄封装）
│       ├── cli.py                      # CLI 工具入口
│       └── mcp_server.py               # Codebuddy MCP Server
├── memory/                             # [NEW] 记忆/知识层
│   ├── chroma_db/                      # ChromaDB 向量存储
│   ├── datasheets/                     # 数据手册知识（按 MCU 分）
│   │   └── stc8h8k64u/
│   ├── ahal_knowledge/                 # A-HAL 代码知识库（按 MCU 分，RAG消费）
│   │   └── stc8h8k64u/
│   │       ├── ahal_api.json           # A-HAL API 规格定义
│   │       ├── usage_examples/         # 使用示例代码
│   │       └── patterns/               # 常见任务模式
│   └── agent_traces/                   # Agent 运行追踪
│       └── 2026-07-05/
├── code/                               # [NEW] 代码层
│   ├── ahal/                           # A-HAL 层（每 MCU 专属目录）
│   │   ├── stc8h8k64u/
│   │   │   ├── gpio.c / gpio.h
│   │   │   ├── uart.c / uart.h
│   │   │   ├── timer.c / timer.h
│   │   │   ├── adc.c / adc.h
│   │   │   └── ...
│   │   ├── stm32f103/                  # [后续]
│   │   └── arduino_mega/               # [后续]
│   ├── vendor/                         # 厂商库函数（只读，不修改）
│   │   ├── stc8h/
│   │   └── stm32/
│   ├── apps/                           # AI Agent 生成的应用代码
│   │   └── generated/                  # 按任务组织
│   └── bsp/                            # 板级支持（SDCC BSP 头文件）
│       └── stc8h8k64u/
│           └── stc8h_sdcc.h
├── tests/
│   ├── hil/                            # HIL 测试用例
│   ├── benchmarks/                     # [NEW] Agent 评测用例
│   │   └── stc8h8k64u/
│   │       ├── gpio_toggle.yaml
│   │       ├── uart_echo.yaml
│   │       └── ...
│   └── py/                             # Python 层单元测试
├── projects/stc8h/Makefile             # SDCC Makefile 模板
└── tools/                              # 辅助脚本
    ├── install_toolchain.py
    ├── fetch_vendor.py
    └── ...
```

## Agent Extensions

### MCP

- **stc-manual**
  - 用途：通过 STC 官方 MCP 查询 STC8H8K64U 数据手册（寄存器定义、外设配置、ISP 协议），支撑 BSP 头文件编写和驱动代码生成
  - 预期结果：获取完整的 SFR 寄存器地址表、GPIO/UART/Timer 配置参数、ISP 烧录协议时序
  - 速率限制：30min/40 次 → 结果必须落盘为 ChromaDB 向量缓存

### Skill

- **skill-creator**
  - 用途：后续开发 Embedded Skills（GPIO 驱动技能、UART 技能等），指导创建符合规范的 Skill 包结构
  - 预期结果：产出结构化的 Skill 定义（manifest + 提示词模板 + 参数 schema）

## 开发阶段计划

### 阶段 0：环境与链路验证（当前）

- 配置 Python venv，安装 stcgal、pyserial、ChromaDB
- 查询 STC8H8K64U SFR 寄存器定义（通过 STC 官方 MCP）
- 编写并手动验证 SDCC 编译点灯程序 + stcgal 烧录成功
- 目录骨架初始化
- **验证点**：手动"编译→烧录→点灯"成功
- **完成标志**：基础物理链路可工作

### 阶段 1：A-HAL 基础 + 核心接口

- 建立 STC8H8K64U SDCC BSP 头文件
- 实现 `providers/base.py` 接口协议
- 开发 A-HAL 最小集（GPIO + UART + delay）
- **验证点**：SDCC 编译 A-HAL 点灯代码成功
- **完成标志**：A-HAL 层可编译运行

### 阶段 2：公共设施

- RAG Service（ChromaDB 向量化手册 + A-HAL 知识）
- HIL Framework（MCU assert 宏 + Python 收集器）
- Agent Tracer（JSONL 任务链路）
- **验证点**：HIL 框架手动验证点灯 PASS/FAIL 判定
- **完成标志**：三设施可独立调用

### 阶段 3：Provider 实现 + CLI 闭环

- STC8H BuildProvider（SDCC Makefile + 日志解析）
- STC8H FlashProvider（stcgal 封装 + 串口检测）
- CLI 适配器 + 最小闭环验证
- **验证点**：`mcu-agent-cli "让 PA0 每 500ms 翻转"` 一键跑通
- **完成标志**：自然语言到硬件验证全自动

### 阶段 4：MCP 适配器 + Skills + Benchmark

- MCP Server 适配器（stdio 协议，接入 Codebuddy）
- Embedded Skills 仓库（GPIO/UART/Timer 模板）
- Benchmark 评测用例集（第一批 5 个标准用例）
- **验证点**：Codebuddy 对话中完成全链路
- **完成标志**：多平台可用 + 可量化评测

### 后续阶段（STM32 / Arduino 扩展）

- 阶段 5-N：按需扩展 STM32F103、Arduino Mega2560 的 A-HAL + Provider + 知识库
- 每扩展一个 MCU 只需：A-HAL 实现 + Provider 适配 + 知识库录入

## 风险矩阵

| 风险 | 等级 | 影响 | 应对 |
|------|------|------|------|
| SDCC 无法编译 STC8H 程序 | 致命 | 阶段 0 阻塞 | 立即验证，失败则评估 Keil C51 免费版 |
| stcgal 对 STC8H 兼容性 | 高 | 烧录不可用 | 阶段 0 优先验证，备选官方 ISP + 串口 |
| STC 官方 MCP 速率限制 | 中 | RAG 更新受限 | ChromaDB 本地缓存，增量更新策略 |
| 硬件在环不稳定（串口干扰） | 中 | 测试误判 | 重试机制 + 超时处理 + 多次采样 |
| A-HAL 接口设计不当需重构 | 中 | 阶段 3 返工 | 阶段 1 先做 GPIO+UART 验证接口合理性 |
| STM32F103 开发板延迟采购 | 低 | 阶段 5 延期 | 当前不依赖，STC8H 先行 |

---

> 本文档为项目总体规划，后续各阶段的具体实施方案将在此基础上展开。
