# Arduino 线开发规划 — 阶段 1：Agent 核心框架搭建

> 版本：v1.0 | 日期：2026-07-09 | 基于总体规划 v2.3

## 一、当前状态基线

| 维度 | 状态 |
|------|------|
| 架构设计 | v2.3 定型（六层 + board顶层 + 裸工具链 + AHL退役） |
| 工具链 | avr-gcc 14.1.0 + avrdude 8.1（手动实证通过） |
| Arduino验证 | blink ✅ + serial_echo ✅（裸avr-gcc，非Arduino API） |
| Agent代码 | **零行**（mcu_agent/ 目录不存在） |
| Skill仓库 | 不存在（仅 .workbuddy/skills/SKILLS.md 含14条操作经验） |
| 知识库数据 | 不存在（kb/ 目录不存在） |
| 架构债务 | P0四项待偿还（反思步、安全闸、前端仿真、去AHL化） |

## 二、资源分层问题的解决方案

### 问题诊断

当前资源散落在不同目录，缺少清晰归属：

| 资源 | 当前位置 | 问题 |
|------|---------|------|
| AI操作经验 | `.workbuddy/skills/SKILLS.md` | 与代码模板/板级配置混在一起 |
| 编译脚本 | `boards/*/apps/*/Makefile` | 散落在各应用目录，不可复用 |
| 烧录脚本 | `boards/*/apps/*/*.py` | 同上 |
| 串口验证 | `boards/*/apps/*/verify_serial.py` | 同上 |
| 项目规则 | `.workbuddy/PROJECT_RULES.md` | 与记忆混放 |
| 知识库协议 | `docs/` | 使用了已退役的AHL术语 |

### 分层原则（四象限）

```
         ┌──────────────────────┬──────────────────────┐
         │   Agent 操作侧        │   数据/定义侧          │
    ┌────┼──────────────────────┼──────────────────────┤
    │ AI │ .workbuddy/skills/   │ .workbuddy/memory/   │
    │ 层 │ → AI操作手册          │ → 项目记忆             │
    │    │ → 编译/烧录经验       │ → 规则/约定            │
    ├────┼──────────────────────┼──────────────────────┤
    │MCU │ mcu_agent/           │ skills/ + kb/        │
    │ 层 │ → 框架代码(Python)    │ → Skill定义(YAML)     │
    │    │ → 工具链封装          │ → 知识库(JSON+ChromaDB)│
    └────┴──────────────────────┴──────────────────────┘
```

**四象限规则**：

1. **`.workbuddy/skills/`** — **WorkBuddy AI 操作知识**。怎么调编译器、怎么检测COM口、avrdude路径坑。AI的操作手册，不是MCU的领域知识。
2. **`mcu_agent/`** — **Agent 框架 Python 代码**。编排器、状态机、Provider、工具链封装、验证引擎。HOW the agent works。
3. **`skills/`** — **MCU Skill 定义（YAML/JSON）**。WHAT the agent can do。"生成blink""生成串口回显"，每个Skill包含模板引用、校验规则、测试用例。
4. **`kb/`** — **知识库数据（JSON + ChromaDB）**。API参考、寄存器表、引脚映射、时钟配置。REFERENCE data。

**关键区分**：
- `.workbuddy/skills/SKILLS.md` ≠ `skills/` — 前者是"怎么用avrdude"，后者是"怎么生成Arduino blink代码"
- `.workbuddy/memory/` ≠ `kb/` — 前者是"我们做过什么决策"，后者是"ATmega2560的寄存器有哪些"

### 存储映射表

| 资源类型 | 存储位置 | 格式 | 说明 |
|----------|---------|------|------|
| AI操作经验 | `.workbuddy/skills/SKILLS.md` | Markdown | avrdude路径坑、COM检测等 |
| 项目规则 | `.workbuddy/PROJECT_RULES.md` | Markdown | 14条不可违背规则 |
| 项目记忆 | `.workbuddy/memory/` | MD + YYYY-MM-DD | 决策记录、工作日志 |
| 框架代码 | `mcu_agent/` | Python包 | 编排器、Provider、工具链 |
| Skill定义 | `skills/` | YAML/JSON | codegen/review/test/verify |
| 代码模板 | `mcu_agent/codegen/templates/` | Jinja2 | 按vendor组织 |
| 知识库数据 | `kb/` | JSON + ChromaDB | API/寄存器/引脚/示例 |
| 板级配置 | `boards/<board>/board.json` | JSON | 已有，保持不变 |
| 芯片库 | `vendor/<chip>/` | C/ASM | 已有，保持不变 |
| 测试脚本 | `boards/<board>/apps/<app>/` | Python/C | 应用专属验证 |
| 设计文档 | `docs/` | Markdown | 规划、评审、协议 |

## 三、Agent 框架模块清单

### 3.1 目录结构（目标）

```
MCU/
├── mcu_agent/                    # Agent 框架 Python 包（全新增）
│   ├── __init__.py
│   ├── core/                     # L2: 智能体核心层
│   │   ├── __init__.py
│   │   ├── orchestrator.py      # 主工作流编排
│   │   ├── state_machine.py     # 状态机 + 错误恢复 + 反思步
│   │   ├── context.py           # 会话上下文管理
│   │   └── safety.py            # 操作安全闸
│   │
│   ├── providers/               # L5: MCU 提供者层（分治边界）
│   │   ├── __init__.py
│   │   ├── base.py              # 抽象基类 ⚠️ 必须守住的边界
│   │   └── arduino/
│   │       ├── __init__.py
│   │       └── provider.py      # Arduino 实现
│   │
│   ├── codegen/                 # L4子模块: 代码生成
│   │   ├── __init__.py
│   │   ├── generator.py         # 生成引擎
│   │   ├── validator.py         # 编译前静态校验
│   │   └── templates/
│   │       └── arduino/
│   │           ├── blink.ino.j2
│   │           └── serial_echo.ino.j2
│   │
│   ├── toolchain/               # L4子模块: 工具链抽象
│   │   ├── __init__.py
│   │   ├── compiler.py          # 编译器抽象接口
│   │   ├── flasher.py           # 烧录器抽象接口
│   │   ├── detector.py          # 工具链/端口自动检测
│   │   ├── verifier.py          # 串口/GPIO验证
│   │   └── arduino/
│   │       ├── __init__.py
│   │       ├── avr_gcc.py       # avr-gcc 编译实现
│   │       └── avrdude.py       # avrdude 烧录实现
│   │
│   ├── kb/                      # L3子模块: 知识库加载
│   │   ├── __init__.py
│   │   ├── loader.py            # 统一加载入口
│   │   └── board_loader.py      # board.json 加载与查询
│   │
│   └── cli/                     # L1: CLI 入口
│       ├── __init__.py
│       └── main.py              # argparse CLI
│
├── skills/                       # Skill 定义（全新增）
│   ├── codegen/
│   │   └── arduino/
│   │       ├── blink.yaml        # "生成Arduino blink"
│   │       └── serial_echo.yaml  # "生成串口回显"
│   ├── review/
│   │   └── arduino/
│   │       └── arduino_rules.yaml
│   ├── test/
│   │   └── arduino/
│   │       └── serial_echo_test.yaml
│   └── verify/
│       └── arduino/
│           └── serial_verify.yaml
│
├── kb/                           # 知识库数据（全新增）
│   └── arduino/
│       └── mega2560/
│           ├── board.json       # → 引用 boards/arduino_mega/board.json
│           ├── api.json         # Arduino API 参考
│           └── examples.json    # 示例代码片段
│
├── boards/                       # 已有
├── vendor/                       # 已有
├── docs/                         # 已有
├── tests/                        # 全新增：集成测试
│   └── test_pipeline.py
└── .workbuddy/                   # 已有
```

### 3.2 核心模块职责

#### `core/orchestrator.py` — 主工作流编排

```
用户需求 → [理解意图] → [查板级知识] → [加载Skill] → [生成代码] →
[编译] → [通过安全闸] → [烧录] → [验证] → [反思/纠错]
```

- 输入：自然语言需求 + board名
- 流程：六步流水线（understand → plan → codegen → build → flash → verify）
- 核心：每步有失败回退，错误自动反思重试（最多3次）

#### `core/state_machine.py` — 状态机 + 反思步

- 状态：IDLE → PLANNING → GENERATING → BUILDING → FLASHING → VERIFYING → DONE
- 每个状态有 on_entry / on_exit / on_error 钩子
- 反思步（Reflexion）：错误时自动分析失败原因，生成修正策略
- 这是P0架构债务 #1 的偿还

#### `core/safety.py` — 操作安全闸

- 烧录前：确认目标板型号与代码匹配
- Dry-run模式：展示将执行的命令但不实际运行
- Human-in-the-loop：烧录前可要求人工确认
- 这是P0架构债务 #2 的偿还

#### `providers/base.py` — 抽象基类（分治边界）

```python
class MCUProvider(ABC):
    @abstractmethod
    def get_board_info(self, board: str) -> BoardInfo: ...
    @abstractmethod
    def generate_code(self, intent: Intent, board: BoardInfo) -> Code: ...
    @abstractmethod
    def get_build_command(self, app_path: str, board: BoardInfo) -> BuildConfig: ...
    @abstractmethod
    def get_flash_command(self, hex_path: str, board: BoardInfo) -> FlashConfig: ...
    @abstractmethod
    def get_verify_commands(self, board: BoardInfo) -> List[VerifyTask]: ...
```

#### `providers/arduino/provider.py` — Arduino 实现

- 原则：**不做封装**，直接复用 Arduino API
- 从 board.json 读取引脚信息
- 调用 avr-gcc/avrdude 进行编译烧录
- 使用 Arduino Core（通过 arduino-cli 管理路径，不复制到项目内）

## 四、工作任务清单

### 阶段 1.1：骨架搭建（优先）

| # | 任务 | 产出 | 依赖 | 预计 |
|---|------|------|------|------|
| 1.1.1 | 创建 `mcu_agent/` 目录结构 | 空包骨架 + `__init__.py` | — | S |
| 1.1.2 | 实现 `core/state_machine.py` | 状态枚举 + 转换表 + 反思钩子 | — | M |
| 1.1.3 | 实现 `core/context.py` | 会话上下文（board/意图/历史） | — | S |
| 1.1.4 | 实现 `core/safety.py` | dry-run + confirm + 板型校验 | — | S |
| 1.1.5 | 实现 `core/orchestrator.py` | 六步流水线骨架（桩实现） | 1.1.2-1.1.4 | M |
| 1.1.6 | 实现 `providers/base.py` | 抽象基类接口定义 | — | M |
| 1.1.7 | 实现 `providers/arduino/provider.py` | Arduino Provider 完整实现 | 1.1.6 | L |
| 1.1.8 | 实现 `toolchain/detector.py` | 工具链自动检测 + COM口检测 | — | S |
| 1.1.9 | 实现 `toolchain/compiler.py` + `avr_gcc.py` | avr-gcc 编译封装 | 1.1.8 | S |
| 1.1.10 | 实现 `toolchain/flasher.py` + `avrdude.py` | avrdude 烧录封装 | 1.1.8 | S |
| 1.1.11 | 实现 `cli/main.py` | argparse CLI 入口 | — | S |

### 阶段 1.2：Skill 定义与代码生成

| # | 任务 | 产出 | 依赖 |
|---|------|------|------|
| 1.2.1 | 设计 Skill YAML 规范 | Skill schema 文档 | — |
| 1.2.2 | 创建 `skills/codegen/arduino/blink.yaml` | blink Skill 定义 | 1.2.1 |
| 1.2.3 | 创建 `skills/codegen/arduino/serial_echo.yaml` | serial_echo Skill 定义 | 1.2.1 |
| 1.2.4 | 创建 `skills/review/arduino/arduino_rules.yaml` | Arduino 代码审查规则 | — |
| 1.2.5 | 创建 `mcu_agent/codegen/templates/arduino/blink.ino.j2` | blink 模板 | — |
| 1.2.6 | 创建 `mcu_agent/codegen/templates/arduino/serial_echo.ino.j2` | serial_echo 模板 | — |
| 1.2.7 | 实现 `codegen/generator.py` | 模板引擎 + Skill 调度 | 1.2.1-1.2.6 |
| 1.2.8 | 实现 `codegen/validator.py` | Arduino 语法/结构校验 | — |

### 阶段 1.3：知识库 + 验证

| # | 任务 | 产出 | 依赖 |
|---|------|------|------|
| 1.3.1 | 创建 `kb/arduino/mega2560/api.json` | Arduino Mega API 参考 | — |
| 1.3.2 | 创建 `kb/arduino/mega2560/examples.json` | 示例代码片段 | — |
| 1.3.3 | 实现 `kb/loader.py` + `board_loader.py` | KB 统一加载 | — |
| 1.3.4 | 实现 `toolchain/verifier.py` | 串口验证引擎 | — |
| 1.3.5 | 创建 `skills/verify/arduino/serial_verify.yaml` | 验证 Skill 定义 | — |
| 1.3.6 | 创建 `boards/arduino_mega/apps/serial_echo/serial_echo.ino` | Arduino版串口回显 | — |

### 阶段 1.4：集成测试

| # | 任务 | 产出 | 依赖 |
|---|------|------|------|
| 1.4.1 | 创建 `tests/test_pipeline.py` | 端到端集成测试 | 全部 |
| 1.4.2 | 全流程验证（blink） | 生成→编译→烧录→验证 | 全部 |
| 1.4.3 | 全流程验证（serial_echo） | 生成→编译→烧录→验证 | 全部 |
| 1.4.4 | 错误恢复测试 | 错误模拟 + 反思重试 | 1.4.2-1.4.3 |

### 阶段 1.5：文档清理

| # | 任务 | 产出 | 依赖 |
|---|------|------|------|
| 1.5.1 | 知识库协议去AHL化 | 更新 `知识库协议接口定义.md` | — |
| 1.5.2 | 更新 PROJECT_RULES.md | 补充资源分层规则 | 1.1 |
| 1.5.3 | 整理 `.workbuddy/skills/SKILLS.md` | 精简为纯AI操作经验 | 1.1.8-1.1.10 |

## 五、Arduino 开发板端工作任务

这些是 Arduino Mega 2560 板端需要做的事情：

### 5.1 板级知识完善

| # | 任务 | 说明 |
|---|------|------|
| A1 | 完善 `boards/arduino_mega/board.json` | 补充所有可用引脚（数字I/O、模拟、PWM、中断、I2C、SPI） |
| A2 | 标注引脚约束 | 哪些引脚内部上拉、哪些与其他功能复用、最大电流 |
| A3 | 补充时钟配置 | 16MHz外部晶振、各预分频器值、Timer分配 |

### 5.2 Arduino API 知识库

| # | 任务 | 说明 |
|---|------|------|
| A4 | 整理 Arduino Mega 核心 API | `pinMode/digitalWrite/digitalRead/analogRead/analogWrite` 等 |
| A5 | 整理串口 API | `Serial.begin/print/println/read/available` |
| A6 | 整理时间 API | `delay/millis/micros/delayMicroseconds` |
| A7 | 整理中断 API | `attachInterrupt/detachInterrupt`，标注可用中断引脚 |
| A8 | 整理 I2C/SPI API | `Wire` 和 `SPI` 库基本用法 |
| A9 | 收集常见外设驱动模式 | 按钮去抖、LED PWM调光、ADC采样、串口协议 |

### 5.3 测试程序

| # | 任务 | 说明 |
|---|------|------|
| A10 | serial_echo 改写为 Arduino API 版 | 用 `Serial.begin/println/read` 替代裸寄存器 |
| A11 | blink 改写为 Arduino API 版 | 用 `pinMode/digitalWrite/delay` 替代裸寄存器 |
| A12 | 编写 GPIO 全功能测试 | 输入/输出/上拉/PWM，覆盖所有数字引脚 |
| A13 | 编写 ADC 测试 | 模拟输入读取，验证 10 位精度 |
| A14 | 编写中断测试 | 外部中断触发，测量响应延迟 |

### 5.4 Skill 定义

| # | 任务 | 说明 |
|---|------|------|
| A15 | 定义 blink Skill | YAML: 描述 → 模板引用 → 编译参数 → 验证标准 |
| A16 | 定义 serial_echo Skill | 同上 |
| A17 | 定义 gpio_test Skill | 输入/输出/上拉/PWM 全功能验证 |
| A18 | 定义 adc_test Skill | ADC 读取与精度验证 |

## 六、开发顺序建议

```
阶段 1.1（骨架）
  │
  ├── 1.1.1 目录结构 → 并行 1.1.2/1.1.3/1.1.4/1.1.6/1.1.8
  │       │
  │       ├── 1.1.2 state_machine → 1.1.5 orchestrator
  │       ├── 1.1.6 base.py → 1.1.7 Arduino provider
  │       ├── 1.1.8 detector → 1.1.9 compiler + 1.1.10 flasher
  │       └── 1.1.11 CLI
  │
阶段 1.2（Skill + 模板）
  │
  ├── 1.2.1 Skill规范 → 1.2.2-1.2.3 Skill定义
  ├── 1.2.5-1.2.6 代码模板（并行）
  └── 1.2.7 generator + 1.2.8 validator
  │
阶段 1.3（知识库 + 验证）
  │
  └── 1.3.1-1.3.2 知识库数据 → 1.3.3 loader
  └── 1.3.4 verifier → 1.3.6 Arduino版程序
  │
阶段 1.4（集成测试）
  └── 端到端验证
  │
阶段 1.5（文档清理）
  └── 去AHL化 + 规则更新
```

## 七、关键设计决策

### 7.1 Skill 定义格式

使用 YAML（非 Python 模块），因为：
- 声明式，方便非程序员维护
- 可以被 LLM 直接作为 prompt context 注入
- 与代码模板分离（关注点分离）

```yaml
# skills/codegen/arduino/blink.yaml
name: arduino_blink
type: codegen
vendor: arduino
boards: [arduino_mega]
intent_patterns:
  - "点灯|闪烁|blink|LED"
template: arduino/blink.ino.j2
build:
  fqbn: "arduino:avr:mega"
  f_cpu: 16000000
verify:
  type: gpio
  pin: 13
  expected: "toggling at 1Hz"
```

### 7.2 Arduino Provider 不做封装

Arduino 线遵循**封装最小化**原则：
- Provider 不创建中间 API 层
- 生成的代码直接使用 `pinMode()`、`digitalWrite()` 等 Arduino 标准函数
- Provider 的职责：板级上下文注入 + 编译参数生成 + 烧录命令编排
- 工具链层负责实际的 avr-gcc/avrdude 调用

### 7.3 现有验证脚本的归宿

| 现有脚本 | 归宿 | 原因 |
|----------|------|------|
| `auto_build_flash_verify.py` | 拆入 `mcu_agent/toolchain/` + `core/orchestrator.py` | 其逻辑是 Agent 的核心流水线 |
| `verify_serial.py` | 拆入 `mcu_agent/toolchain/verifier.py` | 验证逻辑是公共设施 |
| `serial_echo/main.c` | 保留在 `boards/` 作为参考，新增 `.ino` 版本 | 裸C版是历史参考 |
| `flash_stm32.py` | 保留在 STM32 app 目录 | 属于 STM32 线，后续迁移到 toolchain |

### 7.4 编译方式选择

Arduino 线编译有两种方式：
- **方式A**: avr-gcc 裸编译（当前方式，无 Arduino Core 依赖）
- **方式B**: arduino-cli 编译（使用 Arduino Core + libraries）

阶段性策略：阶段1使用**方式B**（arduino-cli），因为：
- 可以直接使用 `Serial`、`Wire`、`SPI` 等库
- 自动处理 FQBN、variant、core 依赖
- 生成的代码直接用标准 Arduino API

方式A（裸 avr-gcc）作为**备选降级路径**保留。

## 八、风险与对策

| 风险 | 影响 | 对策 |
|------|------|------|
| arduino-cli 网络依赖（下载 core） | 编译失败 | 预缓存 Arduino AVR Core 到本地 |
| LLM 生成代码质量不稳定 | 编译失败/运行异常 | validator 预检 + 反思重试 + 最大3次迭代 |
| 烧录到错误板子 | 硬件损坏 | safety.py 的板型校验 + human-in-the-loop |
| 串口验证不稳定 | 假阴性 | 重试机制 + 超时 + 详细错误日志 |
