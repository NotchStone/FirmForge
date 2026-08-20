# FirmForge v3.1 — 项目总体规划

> **更新**：2026-08-20（v3.0 → v3.1：命名统一 run/Verify、数据目录迁入 firmforge/data、并入串口面板架构章节；文件名固定不带版本号）
> **定位**：AI Coding Agent 的 MCU 代码硬件对齐工具链。
> FirmForge 不生成代码、不规划任务——只做两件事：
> 在 Agent **写代码前**提供合法寄存器/引脚/波特率参考，
> 在 Agent **写完后**做寄存器门禁、编译、烧录与串口行为验证。

---

## 一、项目定位

### 一句话

**FirmForge —— 面向 AI 编码 Agent 的 MCU 固件验证工具链：Agent 编写代码，FirmForge 以知识库约束、真实编译与硬件验证确认其可用性。**

### 生态位

FirmForge 处于 AI 辅助嵌入式开发链路的验证环节，作为被 Agent 调用的工具链存在，不承担代码生成与任务规划。

```
用户 → CodeBuddy / Cursor（Agent，负责理解意图、规划任务、编写代码）
              │
              ├─ 写代码前 → ff_detect / ff_context（获取板级硬件参考）
              ├─ 写代码后 → ff_run（门禁 → 编译 → 烧录 → 验证）
              └─ 任何阶段 → ff_detect（探索硬件环境）
```

### 功能与应用场景

FirmForge 提供三项核心能力：

- **编码前约束**：芯片级知识库（寄存器/引脚/波特率）向 Agent 提供合法参考，从源头预防幻觉性错误
- **编码后验证**：五阶段流水线（Detect → Review → Build → Flash → Verify），对固件源码执行静态审查、真实编译、硬件烧录与串口行为验证
- **人机共验闭环**：自动化阶段结果与浏览器实时面板（串口/Modbus）构成完整验证证据链，最终判定由人完成

适用场景：AI 编码 Agent 在 IDE 中为 Arduino（ATmega2560/328P）等 MCU 编写固件时，作为提交给硬件的最后一道验证关卡。

### 设计思想

- **确定性验证**：真实工具链（gcc/avrdude）为守门员，静态检查（Cppcheck/寄存器查证/置信度评分）仅提供参考信息，不替代编译与硬件验证
- **知识驱动**：寄存器/引脚引用以芯片知识库为唯一真相源，编译前拦截幻觉，预防优于检测
- **可扩展**：平台能力经提供者（Providers）契约接入，核心流水线保持稳定，支持多 MCU 平台扩展

### 边界

FirmForge 不承担：

- 任务规划与代码生成（由 Agent 完成）
- 端到端全流程托管（编码在 IDE 中由 Agent 完成）

---

## 二、核心架构

### 双触点设计

```
触 点 1（编码前）              触 点 2（编码后）
ff_context(board, topic?)      ff_run(board?, app, expected?)
                               ff_build(board?, app)   ← 仅编译，无需硬件

返回：寄存器列表                 流程：Detect → Review → Build → Flash → Verify
      引脚映射                        │
      时钟频率                  Source Review（寄存器引用门禁）
      Flash 大小               Confidence Scoring（波特率/引脚评分）
      外设特性                  avr-gcc / arm-none-eabi-gcc 编译
                               avrdude / openocd 烧录
                               串口回读 → 行为验证（人机共验，不阻断）
```

两个触点共享同一个**知识库**（芯片级寄存器参考），一次预防、一次检测。

### 层次架构

```
入口层 (Adapters)       CLI: ff detect | ff build | ff run | ff flash | ff setup
                        MCP: ff_detect | ff_context | ff_build | ff_run | ff_flash | ff_monitor
                              │
编排层 (Orchestrator)   pipeline_runner.py  5 阶段调度 + 指纹增量跳过
                        pipeline_state.py   state.json 状态管理
                        experience_ledger.py  编译失败经验记录
                              │
          ┌───────────────────┼───────────────────┐
          ▼                   ▼                   ▼
验证层 (Validation)     知识库 (Knowledge)      提供者层 (Providers)
source_reviewer.py      knowledge_base.py       providers/__init__.py   ← 注册表
confidence_scorer.py    knowledge/              providers/base.py       ← 抽象边界
board_detector.py         registers.json        providers/arduino/      ← 平台实现
                          pins.json             providers/com_port.py   ← 共享串口
```

**依赖方向**：单向向下。上层不感知底层细节。

---

## 三、MCP 工具集（6 个）

### `ff_detect`
```
扫描 USB 端口，发现连接的 MCU 开发板。
返回：board_id, boards[], candidates[], detected
```

### `ff_context`
```
返回板子的合法寄存器列表、引脚映射、时钟频率、Flash 大小、外设特性。
Agent 写代码前调用，确保所有寄存器名/引脚号来自合法集合。

参数：
  board: 板子 ID。可选，不传则内部自动检测
  topic: 可选过滤（uart/spi/i2c/adc/timer/pwm/gpio）

返回：
  board, chip, clock_hz, flash_size, features
  registers[]: {name, address, size, description, fields[]}
  pins: {arduino_pin: {port, bit, ...}}
```

### `ff_build`
```
仅编译——Review + Build，不需要硬件连接。
用于 CI/pre-commit 检查。

参数：
  board: 板子 ID（可选）
  app:   源码目录路径（必须）

返回：overall_success, board, stages[]
```

### `ff_run`
```
审查 → 编译 → 烧录 → 测试。Agent 写完代码后调用的全流程验证。

参数：
  board:    板子 ID（可选）
  app:      源码目录路径（必须）
  expected: 可选的串口输出正则模式

返回：
  overall_success, board, total_elapsed_ms, stages[]
  stages[].sub_stages: [review, confidence]
  stages[].compile_rounds, matched_baud, pattern_match, expected, actual
```

### `ff_flash`
```
快速重烧——直接烧录预编译的 firmware.hex，绕过 Review+Build。

### `ff_monitor`

串口实时监控面板。独立子进程读串口数据 → 写 serial_live.html → Agent 用 present_files 打开面板。详见 S5 Verify 节。
仅用于已知正确的 hex 文件。
```

---

## 四、CLI 命令（5 个）

| 命令 | 对应 MCP | 作用 |
|------|---------|------|
| `ff detect` | ff_detect | 扫描板子 |
| `ff build <board> --app <dir>` | ff_build | 审查+编译 |
| `ff run <board> --app <dir> [--expected <pat>]` | ff_run | 全流程验证 |
| `ff flash <board> --firmware <hex>` | ff_flash | 独立烧录 |
| `ff setup` | — | 一键安装工具链（avr-gcc/avrdude/cppcheck/ArduinoCore） |

> 注：`ff_monitor` 面板功能由 MCP `ff_monitor` + S5 Verify 面板提供，CLI 侧无独立 monitor 子命令。

---

## 五、管道：5 阶段

### S1 Detect — 板子检测（自动）

```
解析 board.json → 探测 COM 端口
```
S1 为自动阶段——有 board_id 直接解析，无则 BoardDetector 扫描。

### S2 Review — 三层源码审查（非阻断）

**定位**：编译前快速扫描，抓 AI 代码常见三类错误。非阻断——gcc 是真正守门员，Review 结果供 Agent 参考。

**三阶段结构**：

| 阶段 | 工具 | 时间 | 检测内容 | 阻断 |
|------|------|:--:|------|:--:|
| Phase 1: Lint | Cppcheck | 1-3s | 数组越界、未初始化变量、死代码、内存泄漏 | ❌ |
| Phase 2: Register | SourceReviewer | 10ms | 幻觉寄存器名（PORTZ、DDRQ 等） | ❌ |
| Phase 3: Confidence | ConfidenceScorer | 5ms | 波特率精度、引脚冲突评分 | ❌ |

**Phase 1 — Cppcheck（静态分析）**：
```
~/.firmforge/toolchains/cppcheck/cppcheck.exe
```
- 自动查找：`PATH` → `~/.firmforge/toolchains/cppcheck/` → winget
- 未安装时优雅降级，返回空列表
- 默认 suppress: missingIncludeSystem, unusedFunction, constParameter
- 实现：`firmforge/providers/arduino/cppcheck.py` → `run_cppcheck()`

**Phase 2 — Register Review（寄存器门禁）**：
| 子步骤 | 说明 |
|--------|------|
| 寄存器审查 | 扫描 ALL_CAPS 标识符，与 registers.json 交叉验证 |
| 位域审查 | 验证 `(1 << UDRE0)` 等移位表达式中的位域名 |
- 不审查：Arduino API 调用（编译器 C++ 类型系统覆盖）
- 不审查：用户自定义标识符、C 关键字
- 注释内容已自动剥离（防止 GND/SIG 等误报）
- 实现：`firmforge/core/source_reviewer.py`

**Phase 3 — Confidence Scoring（置信度评分）**：
- 检查波特率误差、引脚冲突
- 低于阈值产生 warning（不阻断），供 Agent 自主判断

**输出格式**（Agent 解析）：
```json
{
  "cppcheck": [
    {"file": "main.c", "line": 4, "severity": "error",
     "message": "Array 'buf[4]' accessed at index 5"}
  ],
  "warnings": [
    {"register": "DDRQ", "line": 5, "text": "DDRQ = 0xFF;",
     "reason": "not found in ATmega2560 reference library"}
  ],
  "sub_stages": [
    {"name": "cppcheck", "issues": 1},
    {"name": "review", "violations": 1},
    {"name": "confidence", "score": 85}
  ]
}
```

**失败行为**：全部为 warning，不阻断管道。S3 Build 的 gcc 是真正的守门员。

### S3 Build — 编译

```
平台工具链编译源码 → 生成 firmware.hex
```

**失败行为**：返回完整编译错误 + compile_rounds 计数，阻断后续。
**成功输出**：firmware_path + elapsed_build_ms。

### S4 Flash — 烧录

```
烧录 firmware.hex 到目标芯片
```

特性：
- 自动检测 COM 端口
- bootloader 波特率自适应
- CH340 全版本驱动兼容
- 指纹驱动跳过（board/port/hex 均未变化 + flash 之前成功过）

### S5 Verify — 串口行为验证（人机共验，非阻断）

```
打开串口 → 自适应探测波特率 → 读输出 → 匹配预期模式
```

特性：
- 读取前刷新输入缓冲区
- 自适应读取窗口：上限 5s，读满 2 行可打印数据提前退出
- `expected` 参数：正则模式匹配。结果记录于 `stage.details["pattern_match"]`，**不改变 stage.success**
- **定位**：S5 是流水线最后阶段，自动化采样 + 浏览器实时面板（人）共同验证——烧录成功即阶段 PASS，串口内容由人判断，不因 expected 不匹配阻断

**串口输出展示**：

| 机制 | 文件/工具 | 用途 |
|------|------|------|
| ff_run 快照 | `_write_serial_summary()` → `serial_live.html` | 流程结束展示首帧数据（静态） |
| ff_monitor 实时面板 | `serial_collector.py` → 独立子进程 | 持续读串口 → 实时轮询 HTML 面板 |

**ff_monitor 实时面板方案**：

```
Agent: ff_monitor COM4 9600 start
                        ↓
serial_collector.py（独立子进程，DETACHED）
  ├─ 读串口 COM4 @ 9600
  ├─ 有数据 → 写 serial_live.html（数据 + JS 轮询代码）
  └─ 停止: ff_monitor stop → 创建 .stop 哨兵文件
                        ↓
Agent: present_files(serial_live.html)
                        ↓
右侧面板: JS 每 500ms fetch(location + ?t=cachebuster, cache:no-store)
  ├─ 行数变化 → DOM 替换（无整页刷新）
  ├─ scrollTop = scrollHeight → 自动滚底
  ├─ 状态灯: <3s 绿色, >3s 红色
  └─ 唯一依赖: present_files 对带时间戳 URL 返回最新磁盘文件
```

**`ff_monitor` MCP 输入参数**：

| 参数 | 类型 | 说明 |
|------|------|------|
| `port` | string | COM 端口 (e.g. COM4) |
| `baud` | int | 波特率 (默认 9600) |
| `action` | string | `start` 开始 / `stop` 停止 |

---

## 六、关键技术要素

### 6.1 知识库（芯片级目录）

```
firmforge/knowledge/
├── api/
│   └── avr/api.json              ← AVR Arduino API 合约（目录占位）
└── reference/
    └── avr/
        ├── atmega2560/
        │   ├── registers.json    ← 202 寄存器（含 GCC 别名）
        │   └── pins.json
        └── atmega328p/
            ├── registers.json    ← 91 寄存器（含 GCC 别名）
            └── pins.json
```

每个芯片一个目录，`registers.json` + `pins.json`。格式统一：
- 寄存器：name, address, size, description, fields[]
- 位域：name, bit, access, reset, description
- 顶层：$schema, $id, platform, mcu, version, source, license

### 6.2 多板检测

- USB VID/PID 扫描（仅官方 Arduino/ST-Link，排除 CH340/FT232 等通用桥）
- AVR 芯片探针（avrdude signature 硬件直读——最权威身份识别）
- 工作区推断（source code 寄存器分析——零硬件依赖）
- 多板同时连接时独立区分

### 6.3 CH340 全版本驱动兼容

| 驱动版本 | 策略 |
|----------|------|
| 3.5 | pyserial fast path |
| 3.9 / 4.0 | Win32Serial ctypes fallback，toggle 自愈 |

`ComPort` 上下文管理器（`providers/com_port.py`）自动选择。

### 6.4 指纹驱动增量管道

`state.json` 记录 board_id / port / source / hex 四指纹：

| 指纹变化 | 影响 |
|----------|------|
| source 变化 | Review + Build + Flash + Verify 重跑 |
| hex 变化 | Flash + Verify 重跑 |
| port 变化 | Flash + Verify 重跑 |
| board_id 变化 | 全部重跑 |
| 所有匹配 | 全部跳过 |

跳过 Flash/Verify 需额外条件：state 中记录了 flash=done。

---

## 七、平台扩展契约

**核心代码（永不动）**：pipeline_runner.py, pipeline_state.py, source_reviewer.py, confidence_scorer.py, board_detector.py, experience_ledger.py, knowledge_base.py, providers/base.py

**加新 MCU 平台 = 1 行 + 5 文件**：

| 文件 | 改动 |
|------|------|
| `providers/__init__.py` | +1 行注册表 |
| `providers/stm32/build.py` | 新建——实现 BuildProvider |
| `providers/stm32/flash.py` | 新建——实现 FlashProvider |
| `firmforge/data/boards/stm32_xxx/board.yaml` | 新建——板级配置 |
| `firmforge/data/knowledge/reference/stm32/<chip>/registers.json` | 新建——芯片寄存器 |
| `firmforge/data/knowledge/reference/stm32/<chip>/pins.json` | 新建——芯片引脚 |
| `firmforge/data/vendor/manifests/vendors/stm32_cube_f1.yaml` | 新建——包清单 |
| `firmforge/data/vendor/manifests/tools/{arm_gcc,openocd}.yaml` | 新建——工具链清单 |

---

## 八、目录结构

```
C:\MyLab\MCU\                        ← A区（git 跟踪）
├── ff.cmd / ff.ps1                  ← CLI 启动脚本
├── pyproject.toml                   ← 打包配置（setuptools）
│
├── firmforge/                       ← Python 核心包（pip 随包发布）
│   ├── adapters/
│   │   ├── cli.py                   ← CLI: detect/build/run/flash/setup
│   │   ├── mcp_server.py            ← MCP: 6 工具 × 6 handler
│   │   └── panel_service.py         ← 串口面板 HTTP 服务（9878-9887）
│   ├── core/                        ← ★ 核心稳定，新平台永不动
│   │   ├── pipeline_runner.py       ← 5 阶段调度 + 唯一串口采集线程
│   │   ├── pipeline_state.py        ← state.json 指纹增量
│   │   ├── board_detector.py        ← USB/COM 扫描 + 板子识别
│   │   ├── source_reviewer.py       ← Source Review（寄存器幻觉检查）
│   │   ├── confidence_scorer.py     ← 置信度评分
│   │   ├── experience_ledger.py     ← 编译失败记录
│   │   └── resources.py             ← 包内数据定位（cwd 无关）
│   ├── infrastructure/
│   │   ├── hil.py                   ← HIL 框架（预留）
│   │   ├── tracing.py               ← 调用追踪/日志
│   │   ├── platform_config.yaml     ← 平台配置（包路径、工具链版本）
│   │   └── toolchains_README.md     ← 工具链安装指引
│   ├── knowledge/
│   │   └── knowledge_base.py        ← 知识库查询接口
│   ├── data/                        ← ★ 包内数据（随 wheel 分发）
│   │   ├── boards/                  ← 板定义（board.yaml）+ 示例用例
│   │   │   ├── arduino_328p/        ← ATmega328P 板定义 + apps
│   │   │   └── arduino_mega/        ← ATmega2560 板定义 + apps
│   │   ├── knowledge/               ← 芯片知识库（reference/<platform>/<chip>/）
│   │   │   ├── api/avr/api.json     ← AVR API 合约（目录占位）
│   │   │   └── reference/avr/       ← atmega2560/atmega328p registers+pins
│   │   └── vendor/manifests/        ← ★ 工具链/核心包唯一真相源
│   │       ├── core/arduino_avr_core.yaml
│   │       └── tools/{avr_gcc,avrdude,cppcheck}.yaml
│   ├── tools/                       ← 面板资源 + 工具模块
│   │   ├── panel.html               ← 串口+Modbus 面板（单文件双标签）
│   │   ├── serial_collector.py      ← 串口采集（独立子进程）
│   │   └── modbus_utils.py          ← Modbus CRC/编解码
│   └── providers/                   ← ★ 平台扩展点
│       ├── __init__.py              ← 工厂注册表
│       ├── base.py                  ← 抽象边界（BuildProvider/FlashProvider/TestProvider）
│       ├── com_port.py              ← 跨平台串口（pyserial + Win32Serial fallback）
│       ├── win32serial.py           ← Win32Serial ctypes 实现（CH340 驱动兼容 fallback）
│       └── arduino/                 ← Arduino 实现
│           ├── build.py             ← avr-gcc 编译（裸编 + ArduinoCore 两路线）
│           ├── cppcheck.py          ← Cppcheck 静态分析（S2 Phase 1）
│           ├── flash.py             ← avrdude 烧录
│           ├── setup.py             ← ff setup 工具链安装器（跨平台）
│           ├── test.py              ← HIL 测试适配器（预留）
│           └── toolchain.py         ← 工具链路径解析（canonical→PATH→fallbacks）
│
├── tests/                           ← 单元测试 + 基准测试（214 passed）
│   ├── test_board_detector.py
│   ├── test_source_reviewer.py
│   ├── run_bench_fixed.py
│   └── ...
│
├── docs/
│   ├── FirmForge-总体规划.md           ← 本文档（版本见文件头，文件名固定）
│   └── test_benchmark/                 ← 基准测试数据
│
└── .gitignore                      ← *.hex *.elf *.o .firmforge/ dist/ 等

~/.firmforge/                       ← B区（用户区，ff setup 按需下载）
├── toolchains/                     ← 编译器/烧录器二进制
│   ├── avr-gcc/                    ← avr-gcc.exe + avr-libc
│   └── avrdude/                    ← avrdude.exe + avrdude.conf
├── packages/                       ← 平台 SDK（按 manifest 下载）
│   └── arduino/avr/1.8.6/          ← ArduinoCore-avr
│       ├── cores/arduino/          ← Arduino.h 核心
│       ├── libraries/              ← 11 个内置库
│       └── variants/               ← 11 种板型引脚映射
└── cache/                          ← 编译产物
    ├── build/<board>/<app>/        ← firmware.hex
    └── preprocess/                 ← .ino 预处理中间文件
```

---

## 九、工具链与包管理

### 9.1 工具链（编译器/烧录器 → B区 toolchains/）

| 工具 | 版本 | 用途 |
|------|------|------|
| avr-gcc | 14.1.0 | AVR 编译 |
| avrdude | 7.2/8.1 | AVR 烧录（ZakKemble 包内置 7.2，可系统安装 8.1） |
| cppcheck | 2.21.0 | S2 Review 静态分析（Windows MSI 提取） |
| arm-none-eabi-gcc | 14.2.Rel1 | STM32 编译（待集成） |
| openocd | 0.12.0 | STM32 调试/烧录（待集成） |

安装路径：`~/.firmforge/toolchains/`。运行 `ff setup` 按 `firmforge/data/vendor/manifests/tools/*.yaml` 下载（幂等）。

### 9.2 平台 SDK（头文件/库 → B区 packages/）

| 包 | 版本 | 路径 |
|------|------|------|
| ArduinoCore-avr | 1.8.6 | `~/.firmforge/packages/arduino/avr/1.8.6/` |

按 `vendor/manifests/core/arduino_avr_core.yaml` 定义。新平台接入时按同模式扩展。

### 9.3 搜索优先级

Core 头文件/库：B区 packages → A区 vendor fallback
工具链二进制：canonical → PATH → mcu-tools → winget

---

## 十、当前状态

### 已完成

| 功能 | 状态 |
|------|------|
| CH340 全版本驱动兼容 | ✅ |
| 多板同时检测与区分 | ✅ |
| 串口波特率自适应 + bootloader fallback | ✅ |
| 芯片签名优先（avrdude 硬读） | ✅ |
| 工作区推断（零硬件依赖） | ✅ |
| Source Review（寄存器+位域幻觉拦截） | ✅ |
| Confidence Scoring（波特率/引脚评分） | ✅ |
| avr-gcc 裸编译 + ArduinoCore 两路线 | ✅ |
| .ino 预处理（原型注入 + 注释剥离 + C→C++ 转换） | ✅ |
| 串口输出回读 + 模式匹配 | ✅ |
| 实时串口面板（ff_monitor） | ✅ 2026-07-25 |
| 指纹驱动增量管道（state.json） | ✅ |
| compile_rounds 计数器 | ✅ |
| 平台工厂注册表 | ✅ |
| 芯片级知识库（328P 91 / 2560 202 寄存器） | ✅ |
| Arduino UNO / Mega / Nano 全覆盖 | ✅ |
| manifest 驱动架构（vendor/manifests/ 为真相源） | ✅ |
| 构建产物统一到 B区 cache/（A区零污染） | ✅ |
| board.json → board.yaml 迁移 | ✅ |
| build artifacts 清理（637 个 .hex/.elf 移除） | ✅ |
| 单元测试全通过（155 → 214） | ✅ 2026-08-19 |
| flash.py shell=True 消除 + 消重 | ✅ |
| pyproject.toml 合法化（build-backend + 描述） | ✅ |
| vendor/ 按平台分组（arduino/ + stm32/） | ✅ |
| 数据资源迁入包内 firmforge/data/（pip 化，cwd 无关） | ✅ 2026-08-19 |
| ff setup 工具链安装器（avr-gcc/avrdude/cppcheck/Core） | ✅ 2026-08-19 |
| 串口面板 + Modbus RTU 面板 | ✅ 2026-08-18 |
| wheel 构建 + 安装态验证（任意目录 ff run 全链路） | ✅ 2026-08-19 |
| GitHub/Gitee 双仓发布（README EN/CN） | ✅ 2026-08-20 |

### 待扩展

- STM32 提供者实现（build.py + flash.py）
- STM32 芯片知识库（registers.json + pins.json）
- 行为验证 DSL
- PyPI 发布（命令 `pip install firmforge`，当前走 GitHub/Gitee git+https）

---

## 十二、代码质量与技术债务 To-Do

> 基于 2026-07-22 全量代码评审结果，按优先级排列。

### P0（阻断正确性/可维护性）
| ID | 项 | 状态 |
|:--:|------|:--:|
| T1 | `pyproject.toml` build-backend 非法 | ✅ 已修复 |
| T2 | `pyproject.toml` 描述去 Agent | ✅ 已修复 |
| T3 | `flash.py` shell=True → list+cwd | ✅ 已修复 |
| T4 | `build.py` 1.8.6 硬编码 → manifest 读取 | ⬜ config 已就位，代码 TODO 已标注（STM32 时读 manifest） |
| T5 | `build.py` 裸编递归 glob 源文件（子目录多文件工程） | ✅ 已修复（rglob） |
| T6 | `build.py` .cpp 文件用 avr-g++ 而非 avr-gcc | ⬜ TODO 已标注（需 toolchain.py 支持 avr-g++ 解析） |
| T7 | `confidence_scorer` 328P 波特率评分失效（board_id 默认 mega） | ✅ 已修复（pipeline 传 board_id + chip 推断 fallback） |
| T8 | `source_reviewer` 白名单数据化（STM32 时完成） | ⬜ STM32 接入时 |
| T9 | Core 编译 `.o` 按版本缓存 | ✅ 已实现（packages/avr/1.8.6/build/{mcu}/core.a，SHA256 哈希 + manifest.json） |
| T10 | `build.py` 硬编码宏 `-DARDUINO=10607` | ⬜ TODO 已标注，值已入 config（同 T4） |
| T11 | `confidence_scorer` 阈值 `58.0` 进配置 | ✅ 已修复（pipeline_runner 读取 yaml → 传入 ConfidenceScorer） |
| T12 | `confidence_scorer` 不验证寄存器赋值正确性（浅评分） | ⬜ 设计意图（仅查幻觉名，不查值），保持 |
| T13 | `source_reviewer` bit-field 宏误报噪音 | ⬜ STM32 时评估 |

### P2（平台扩展与 CI）
| ID | 项 | 状态 |
|:--:|------|:--:|
| T14 | build/flash 核心链路集成测试（mock serial/avrdude） | ✅ 已添加 23 个测试（test_build.py + test_flash.py） |
| T15 | GitHub Actions CI（lint + pytest + smoke build） | ✅ 已添加 `.github/workflows/ci.yml` |
| T16 | STM32 provider 完整实现（build/flash/toolchain） | ⬜ AVR 稳定后启动 |
| T17 | manifest reader（package_manager.py + manifest_parser.py） | ⬜ STM32 时一并实现 |
| T18 | `knowledge_base` registers/pins 键空间统一（多平台碰撞风险） | ⬜ STM32 接入前处理 |
| T19 | `pipeline_runner` 多文件拼接致行号失真 | ⬜ 低优，留待观察 |
| T24 | `pipeline_runner` KnowledgeBase 重复加载（D10） | ✅ 已修复（`_load_knowledge_base` 单次缓存，SR/Confidence 共享） |
| T25 | 构建中间产物残留（.elf + preprocess .ino） | ✅ 已修复（try/finally + `_clean_stale_artifacts`） |

### P0 补充（本轮验收新发现-已修）
| ID | 项 | 状态 |
|:--:|------|:--:|
| T20 | `flash.py` MCU_MAP fallback m2560 危险（未知芯片误映射） | ✅ 改为 raise FlashError |
| T21 | `confidence_scorer` docstring "safety gate" → "warning only" | ✅ 已修正 |
| T22 | `pipeline_runner` 置信度漏扫描 .ino 文件 | ✅ 已补充 glob |
| T23 | `pyproject.toml` 缺 pytest 配置 + 可选依赖 | ✅ 已添加 |
| T26 | Core 编译缓存：冷 55s → 热 3s（14x 提升） | ✅ 2026-07-23 已实现 |
| T27 | 官方 Arduino 例程全量编译测试（Mega2560） | ✅ 90/94 通过（2026-07-23） |
| T28 | 官方 Arduino 例程串口全链路验证（Mega2560） | ✅ 8/8 通过（2026-07-23） |
| T29 | 官方 Arduino 例程编译测试（UNO） | ✅ 83/89（2026-07-24） |
| T30 | 库例程编译测试（Mega2560 + UNO） | ✅ 2026-07-24 |
| T31 | .ino 预处理器三项修复（struct 深度、#if 剥离、C 风格声明收缩） | ✅ 2026-07-23 已修复 |
| T32 | Core 编译增加 .S 汇编文件支持 | ✅ 2026-07-23 已修复 |

---
## 十二、Core 编译缓存策略

> 见项目记忆 `.workbuddy/memory/MEMORY.md` 第十一节

### 核心规则
1. 缓存只覆盖 Core + 库源码（~/.firmforge/packages/arduino/avr/1.8.6/ 下的所有 .c/.cpp/.S），不含用户代码
2. 缓存位置与 SDK 包同层级：`packages/avr/1.8.6/build/{mcu}/`
3. 缓存键：从 core_base 的相对路径（如 `cores/arduino/wiring.c`）
4. 失效机制：SHA256 → manifest.json 对照，源码变化自动重编
5. 链接格式：`avr-g++ user.o core.a -o firmware.elf`
6. 跨 MCU 隔离：不同 MCU 各自独立目录，互不干扰

---
## 十三、基准测试体系

### B区例程库（只读）
```
~/.firmforge/examples/
├── arduino/
│   ├── builtin/     ← arduino/arduino-examples（01~11 全系列，81 .ino）
│   └── avr/         ← ArduinoCore-avr libraries/*/examples（79 .ino）
└── stm32/           ← 预留
```

### 测试结果
```
docs/test_benchmark/
├── NL_REQUIREMENTS.json                  ← 50 项测试标准
├── official_examples_20260723.json       ← Mega2560 builtin 编译结果
├── official_examples_arduino_mega_20260723.json   ← Mega2560 完整编译
└── official_examples_arduino_328p_20260723.json   ← UNO 编译结果
```

### 测试流程
1. `ff build <board> --app <example_dir>` — 编译验证
2. `ff run <board> --app <example_dir>` — 全链路（串口例程）
3. 结果输出到 `docs/test_benchmark/official_examples_{board}_{date}.json`

---

## 十一、命名规范

| 场景 | 用词 |
|------|------|
| 项目定位 | MCU 代码验证工具链 |
| 功能描述 | 寄存器门禁 / 引用验证 / 编译烧录测试 |
| MCP 工具 | ff_detect / ff_context / ff_build / ff_run / ff_flash / ff_monitor |
| CLI 命令 | ff detect / ff build / ff run / ff flash / ff setup |
| 管道阶段 | Detect → Review → Build → Flash → Verify |
| 禁止使用 | kb (→ knowledge_base), _sm, 端到端, 全流程, 自然语言编程, Agent, 7-Stage Pipeline, Boot Signature, Citation Gate |

---

## 十四、串口面板架构（Serial + Modbus）

> 原独立文档 `docs/panel-architecture.md`（2026-08-18 更新）并入本文，作为最高纲领组成部分。
> 核心约束：**物理串口唯一** → 只能一个采集线程(collector)

### 14.1 三文件分层

```
┌─ firmforge/tools/panel.html ──────────────── 表示层
│  一个文件, 两个标签(Serial/Modbus), 共用串口控制栏
├─ firmforge/adapters/panel_service.py ─────── 服务层
│  HTTP 路由层, 独立服务(9878-9887 端口回退), 仅面板相关路由
├─ firmforge/core/pipeline_runner.py ────────── 采集层
│  _collector_thread 唯一串口读写线程
```

**panel.html（表示层）**：单文件双标签。Serial 标签：连续串口数据（SSE 推送）、发送栏（文本/HEX + CRLF）、自动滚底、Clear 按标签区分。Modbus 标签：时间线 TX→/RX← 双毫秒时间戳左置 / 解码网格；前端 JS 拼帧+CRC（仅显示），实际发送由后端 `modbus_encode_frame` 重建。共用：串口控制栏（port/baud/parity/Open/Close/Clear）、RX/TX 计数（Modbus 用独立 `mbRx/mbTx`）、阶段状态行/过程信息行。

**panel_service.py（服务层）**：从 mcp_server 拆出的独立 HTTP 服务，端口 9878-9887 回退。路由：

| 路由 | 方法 | 功能 |
|------|------|------|
| `/serial_live.html` | GET | 返回面板 HTML |
| `/stream` | GET | SSE 数据流（3s 心跳，断连不杀 collector） |
| `/serial-send` | POST | 普通串口写入(serial_write.json) |
| `/serial-config` | POST | 波特率/校验位配置(serial_config.json) |
| `/modbus` | POST | Modbus 命令（Queue IPC，5s 超时返回 ok:False） |
| `/serial-open` | POST | 打开串口(移除 .pause) |
| `/serial-close` | POST | 关闭串口(创建 .pause) |
| `/serial-stop` | POST | 停止采集(创建 .stop + .pause) |
| `/quit` | POST | 优雅关闭面板服务(collector 停止 + httpd shutdown) |

**Modbus 队列 IPC**（2026-08-14 迁移，替代原文件管道）：`get_modbus_request_queue()` / `get_modbus_response_queue()` 双 `queue.Queue`；HTTP handler `req_q.put` → `resp_q.get(timeout=5)`；collector `req_q.get(block=False)` → 执行 → `resp_q.put`。延迟 ~60-100ms。

**pipeline_runner.py（采集层）**：`_collector_thread` 主循环——发现 `.stop` 停止；发现 `.pause` 关串口等重开（重开读 serial_config.json 更新 baud/parity）；`serial_write.json` 写入；`_exec_modbus`（原子操作，期间主线采集暂停，响应不被抢读）；`ser.read(64)` → SSE → HTML。

### 14.2 Modbus 交互流程（Queue IPC）

```
panel.js                     panel_service.py             collector thread
拼帧+CRC(仅显示 TX→)  →  POST /modbus ─► req_q.put(data)
                                     resp_q.get(timeout=5)
                                     ←  req_q.get(block=False)
                                        modbus_encode_frame() → ser.write → 阻塞读
                                     →  resp_q.put({raw,regs,...})
面板 ← 返回 {ok, raw, rx, tx} ──────
渲染 RX← + 解码网格 + mbRx/mbTx 累加
```

### 14.3 文件职责边界

- **不动 pipeline_runner.py**：`_exec_modbus` 的串口读/写/CRC 校验、帧结构、采集循环主结构不可改；可改超时/错误处理（表现层）
- **不动 mcp_server.py**：面板路由已迁 panel_service，mcp_server 不再新增面板功能；`_get_stream_queue` 由 mcp_server 转发到 panel_service 保持兼容
- **只动 panel.html**：面板 UI 调试（时间线布局/表单/JS 拼帧 CRC 解码/发送格式）限于 panel.html

### 14.4 功能状态（2026-08-18）

| 功能 | 状态 |
|------|------|
| Serial/Modbus 双标签独立 | ✅ |
| ASCII/HEX/CRLF 发送 | ✅ |
| Modbus FC03/04/06/16 拼帧（后端重建） | ✅ |
| Modbus 解码网格 + 异常响应解码 | ✅ |
| RX/TX 计数器（Modbus 独立变量） | ✅ |
| 波特率/校验位配置生效 | ✅ |
| SSE 相对路径（端口回退兼容） | ✅ |
| Clear 按标签 + 计数器归零 | ✅ |
| 串口关闭时 Modbus 明确报错 | ✅ |
| Open/Close 刷新状态真实反映 | ✅ |
| /quit 优雅退出 | ✅ |

### 14.5 面板测试

- `tests/test_modbus_utils.py`：CRC / encode_frame 四功能码 / decode_response
- `tests/test_panel_service.py`：HTTP 路由（serial-send/config/close/open/modbus）
- `tests/test_exec_modbus.py`：mock serial 测拼帧/解码/ser=None
- `tests/test_collector_baud.py`：serial_config.json 读取
