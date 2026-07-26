# FirmForge 开发日志

## 2026-07-08
- **Arduino Mega2560 blink 编译烧录验证成功**：创建 `boards/arduino_mega/board.json`、blink 程序，PlatformIO 编译通过（Flash 0.6%，52s），avrdude 8.1 烧录验证通过，LED 闪烁成功
- **STM32F103VET6 最小工程搭建**：创建 `boards/stm32f103vet6_minisys/board.json`、`bsp_config.h`、`LinkerScript.ld`、`Makefile`、`apps/blink/main.c`，以及 `vendor/stm32/cmsis/stm32f1xx/startup_stm32f103xe.s` 启动文件
- **规划文档升级 v2.3**：AHL 退役，board 顶层 + vendor 复用架构定型，裸工具链选型确认
- **项目级文件建立**：创建 `PROJECT_RULES.md`（14 条规则）、`SKILLS.md`（11 条经验）

## 2026-07-09
- **裸工具链安装完成**：卸载 PlatformIO，通过 gh-proxy.com 代理安装 avr-gcc 14.1.0（`~/AppData/Local/mcu-tools/avr-gcc/`）、openocd 0.12.0（`~/AppData/Local/mcu-tools/openocd/`），winget 安装 ARM GCC 14.2
- **Arduino Mega2560 纯 C 串口通信闭环**：创建 `boards/arduino_mega/apps/serial_echo/` 程序（USART0 9600 8N1，回显大写转换+心跳，Flash 1082B，RAM 346B），avr-gcc 直接编译，avrdude 烧录，4 项测试全部 PASS
- **自动化脚本**：创建 `auto_build_flash_verify.py`（一键编译→烧录→串口验证）、`verify_serial.py`（独立串口通信验证）、`Makefile`
- **STM32F103VET6 Blink 编译通过**：arm-none-eabi-gcc 14.2 编译成功（Flash 544B），修复新 libc 链接问题（添加 `_init`/`_fini`/`__libc_init_array` 桩函数）；STM32 烧录调试暂停（USART bootloader write_memory 时序异常）
- **产品命名锁定**：英文名 FirmForge，CLI 命令名 `ff`，内部 Python 包 `mcu_agent`（后改为 firmforge）
- **架构命名审计**：knowledge 层重命名（`memory/`→`knowledge/`，包 `mcu_agent.kb`→`mcu_agent.knowledge`，子库 `*_kb/`→`knowledge/reference|api|community/`）

## 2026-07-11
- **核心框架搭建**：创建完整目录树 `firmforge/{core,providers,infrastructure,adapters,knowledge}/` + `skills/{codegen,review,test,verify}/` + `tests/`
- **Provider 分治接口**：实现 `providers/base.py`（BuildProvider/FlashProvider/TestProvider 抽象基类 + BuildResult/FlashResult/TestResult dataclass）
- **Core 模块实现（~1400 行）**：
  - `agent_state_machine.py`：双作用域状态机（MODULE/PROJECT），五态 + COMPILE_FIX_LOOP/FLASH_RETRY
  - `experience_ledger.py`：JSONL 追加式经验账本
  - `context_manager.py`：三层 Token 优化（RESIDENT/SESSION/ON_DEMAND）
  - `board_detector.py`：多路融合检测（USB VID/PID + workspace扫描 + 文本提取）
  - `skill_engine.py`：SkillRouter + SkillEngine 编排层
  - `plan_generator.py`：PlanSpec + draft→reviewed→locked 状态机
- **CLI 实现**：`adapters/cli.py`，argparse 4 命令（ff init/gen/run/flash）
- **基础设施**：`infrastructure/tracing.py`（JSONL 事件追踪）、`knowledge/knowledge_base.py`（占位）
- **Skills 路由文件**：创建 4 个 `_router.md`
- **板级配置更新**：`boards/arduino_mega/board.json` 补充 `constraints` + `features` 字段
- **单元测试 72/72 全部通过**：test_agent_state_machine(14) / test_experience_ledger(11) / test_context_manager(12) / test_board_detector(15) / test_plan_generator(12) / test_skill_engine(8)
- **阶段 2 开发**：创建 `knowledge/api/avr/api.json`（~380 行，8 大类 61 个函数）；重写 `knowledge_base.py`（165 行，load_api/lookup_function/search/get_context_for_codegen）；创建 `infrastructure/hil.py`（265 行，HIL Framework）；创建 `infrastructure/platform_config.yaml`、`infrastructure/validate_skills.py`（275 行）
- **阶段 2 测试**：新增 36 个测试（test_knowledge_base 13 + test_hil 19 + test_validate_skills 8），144/144 全部通过
- **阶段 3 开发**：实现 ArduinoProvider 三层（toolchain检测/build/flash/test，~600 行）；创建 6 个 Skill（gpio_driver/uart_driver/safety_check/hil_assert_gen/compile/flash），全部 CI 验证通过；实现 ToolOrchestrator PipelineRunner（7 阶段串联 + COMPILE_FIX_LOOP）
- **阶段 3 测试**：108/108 测试通过
- **E2E 全链路闭环**：Arduino Mega2560 全部 7 阶段 PASS（8.7s）
- **全项目重命名**：`mcu_agent` → `firmforge`（包名与产品名统一）

## 2026-07-12
- **AVR 寄存器参考库**：创建 `knowledge/reference/avr/registers.json`（~600 行，57 个寄存器定义，含 GPIO 11 端口 + USART 4 组 + 位域）；创建 `knowledge/reference/avr/pins_mega2560.json`（70 个引脚映��� + 4 串口 + 5 波特率预设）
- **KnowledgeBase RRF 融合搜索**：增强 `knowledge_base.py`（+200 行），实现 `ScoredHit` + `hybrid_search()` RRF 融合、寄存器/引脚/波特率精确查找
- **引用门禁 Citation Validator**：创建 `core/citation_validator.py`（~300 行），三阶段检测策略（位域提取→寄存器赋值上下文→广域扫描），幻觉寄存器（PORTZ/UCSR9A/DDRQ 等）编译前阻断，Arduino API 代码无误报
- **测试 191/191 全部通过**：新增 83 个测试（test_reference_library 35 + test_rrf_search 25 + test_citation_validator 23）
- **Citation Validator 集成到 ToolOrchestrator**：`tool_orchestrator.py` 在 Code→Build 间插入 citation gate（+100 行），失败记录经验账本
- **置信度评分 Confidence Scoring**：创建 `core/confidence_scorer.py`（~300 行），寄存器/波特率/引脚三轴评分，阈值 58%，citation 失败强制 ≤30%，集成到流水线
- **测试 232/232 全部通过**：新增 41 个测试（test_tool_orchestrator_integration 14 + test_confidence_scorer 27）
- **CodeGenerator 实现**：创建 `core/code_generator.py`（~350 行），`build_prompt()` 构建含系统前言/任务规格/平台信息/API 参考/寄存器参考/引脚约束/模块结构/安全规则的综合提示词；`save_code()` 解析 LLM 响应写入源码文件
- **首次端到端自然语言开发闭环验证**：自然语言"让LED以2Hz频率闪烁"→Plan 生成→DeepSeek 生成代码→Citation Gate PASS→Confidence 100%→Build PASS→Flash PASS→Test PASS
- **范式推断引擎**：创建 `core/paradigm_resolver.py`（~300 行），5 种范式枚举 + 四级决策（board.json 显式→用户意图关键词→板子身份→MCU 默认），用户意图中英文映射
- **board.json 扩展**：新增 `board_type`/`paradigm`/`mcu.family`/`code_style` 字段
- **测试 262/262**：新增 30 个范式测试
- **Arduino Core 工具链集成**：下载 Arduino AVR Core 源码到 `~/.firmforge/toolchains/`；更新 `build.py` 自动检测 `#include <Arduino.h>`，两步编译（.c→avr-gcc, .cpp→avr-g++），24 个 Core 源文件 + 用户代码；Arduino API 代码全 7 阶段 PASS（17.9s）
- **MCP Server 适配器**：创建 `adapters/mcp_server.py`（~280 行），FastMCP stdio 传输，暴露 ff_init/ff_run/ff_flash 3 个 tool
- **LLM API 集成**：创建 `core/llm_client.py`（~230 行），封装 DeepSeek API（OpenAI 兼容协议），三层安全 API key 查找（env→配置文件→提示），多重 .gitignore 防护
- **AVR 芯片探测**：`board_detector.py` 新增 `_probe_avr()` 方法（avrdude 握手确认芯片签名，Mega2560 95%/UNO 95%）
- **复杂度驱动流水线调度**：`ModuleSpec` 加 `complexity` 字段（standard/driver），`PlanGenerator._derive_modules()` 自动标记，`ToolOrchestrator._analyze_complexity()` 注入调度决策
- **Bug 修复**：PlanSpec 缺少 constraints 属性兼容性；YAML 行尾中文注释解析；CodeGenerator 返回类型不匹配；目录命名改为 ASCII slug；Arduino API 代码自动判断 .cpp 扩展名；端口缓存回退
- **测试 265/265**：新增 3 个 + 修复 2 个

## 2026-07-16
- **Arduino UNO 板级支持**：创建 `boards/arduino_uno/board.json`（ATmega328P, 16MHz, 32KB Flash, 2KB RAM）
- **board_detector.py 多 MCU 支持**：AVR probe 支持多 MCU 试探（m2560→m328p），签名表添加 ATmega328P (0x1E950F→arduino_uno 95%)
- **全局命名规范统一**：`Paradigm.HAL`/`LL`→`Paradigm.STM32`，所有 `_kb`→`_knowledge_base`，公开属性 `validator._kb`→`validator.knowledge_base`，新增 `PROJECT_RULES.md` §R13
- **知识库全面补全**：Arduino API 44→58 函数（12 类，补 max/min/random/tone/pulseIn/shiftOut）；ATmega2560 寄存器 57→127 个（补 Timer/SPI/TWI/EEPROM/ADC/系统/中断/WDT）；ATmega328P 寄存器 15→82 个
- **knowledge/ 目录重组织**：chip 级 → `reference/avr/{atmega2560,atmega328p}/`
- **Arduino UNO 硬件 E2E 测试**：编译通过（avr-gcc 14.1.0, atmega328p + standard variant），avrdude 烧录，串口输出正常
- **CH340 克隆板烧录修复**：flash provider 加 1200 baud DTR 50ms 主动拉低 + 500ms 等待（解决 CH340 驱动 DTR 脉宽不足触发 bootloader 问题）
- **Builder/Flash provider 芯片自适应**：重构为芯片级映射（`_MCU_MAP`/`_VARIANT_MAP`/`_BOARD_DEFINE_MAP`），新增 ATmega32U4/168P/88P/48P 支持模板
- **测试修复**：4 个集成测试（`_stage_init` 硬件检测覆盖显式 board_id）→ 265/265
- **Citation Gate 验证 10/10 通过**（Mega vs UNO 寄存器正确区分）

## 2026-07-17
- **CH340 烧录后串口锁定根因分析与修复**：从"pyserial close 不复位"修正为"CH340 Win11 驱动 SetCommState 同值返回 ERROR_GEN_FAILURE(31)"（非 pyserial bug，驱动缺陷）；**实现 Win32Serial 模块**（`providers/arduino/win32serial.py`，ctypes 自写最小 Win32 serial，open toggle 自愈 + close 恢复残留 115200）
- **链式验证**：脏态残留 9600 → Win32Serial open 9600 toggle 自愈成功 → 外���原生 pyserial 直开 9600 成功（用户原始痛点彻底解决）
- **知识库 bug 修复**：`knowledge_base.py` 引脚结构兼容（`pins.json` dict 与 list 结构兼容，修复 UNO 全部引用门禁阻断）
- **烧录验证**：UNO 心跳+ADC1 程序（`boards/arduino_uno/apps/uart_heartbeat_adc1_1f3c/main.cpp`）全 7 阶段 PASS，串口回读确认每秒 HEARTBEAT #N adc1=值 正常
- **S6 Test 简化**：默认跳过串口测试（`FIRMFORGE_HIL_TEST=1` 启用）；去掉不必要的 115200→9600 切换
- **测试 265/265 + E2E 全部通过**

## 2026-07-18
- **CH340 驱动兼容策略最终定案**：三层兼容保障——pyserial 优先（3.5 良好驱动快速路径），Win32Serial toggle fallback（3.9/4.0 buggy 驱动自动接管），不检测驱动版本自适应；回退过度设计，ComPort/com_port_clean_close 回到 pyserial 为主，Win32Serial 仅作 fallback
- **多板检测与自动识别**：`board_detector.py` detect() 按端口分组 candidates，DetectionResult.boards 列出所有已连接板子；创建 `boards/arduino_nano/board.json`
- **串口波特率自适应（S1+S6）**：`_scan_serial_signature` 遍历 [9600,115200,57600,38400] 自动匹配；`_stage_test` 遍历候选波特率锁定第一个可打印 ASCII 的波特率；S6 从 30 次超时 → ~5s
- **智能 bootloader 波特率适配**：`flash.py` avrdude 115200 失败 → 自动 retry 57600 → 19200；`_get_baud_fallbacks()` 读取 board.json bootloader.fallback_bauds
- **新增测试**：test_board_detector.py 多板检测 + serial sig 波特率 fallback；test_flash_bootloader.py bootloader 波特率 fallback 逻辑；270/270 全通过
- **E2E 验证**：UNO 全 7 阶段 PASS（3.5 驱动快速路径 + 3.9 驱动 fallback 透明）；双板同时检测（COM4 + COM5）正确列出

## 2026-07-19
- **ATmega2560 50 项全量测试**：50 个纯 AVR 寄存器测试程序（GPIO/USART/ADC/Timer/EEPROM/中断/看门狗/SPI/TWI），全部通过 Review + Build（50/50），1 次真实 Flash 执行成功，49 次指纹跳过
- **Bug 修复**：Citation Gate 字符串字面量误扫描（`_strip_strings` 未应用于 Phase 1/2）；GCC 16 位寄存器别名从 `iomxx0_1.h` 解析 25 个注入知识库（OCR1A, TCNT1 等）；Test 阶段跳过已传 expected；Flash 静默通过检测（加 "chip erase failed" 和 "error:" 检测）；Mega bootloader chip erase 失败加 `-D` 跳过擦除；ff_flash 相对路径改 `os.path.abspath()`
- **架构重命名**：`citation_validator.py`→`source_reviewer.py`（CitationValidator→SourceReviewer）
- **API Citation Gate 删除**：移除 `validate_api`/`_api_citation_check`/`load_api`/`lookup_function`/`search`/`hybrid_search` 等，知识库精简
- **Arduino API 编译管线修复**：ArduinoCore-avr 克隆到 `vendor/arduino-avr-core/`；修复 `core_base`/`core_inc`/`variant_inc` 路径嵌套 Bug；分离 Core（-w）与用户代码（-Wall）编译标志；.ino 文件自动函数原型注入
- **Shared 模块提取**：`ComPort` + `com_port_clean_close` → `providers/com_port.py`；`win32serial.py` 从 `providers/arduino/` → `providers/`
- **单元测试 152 passed**

## 2026-07-20
- **Bug 修复（5 个）**：SPI/Wire/EEPROM 库头文件找不到（build.py 添加 libraries/*/src/ 的 -I 路径 + 编译库源码）；`_preprocess_ino` 缺少 `import os`；`.ino` 文件自动注入 `#include <Arduino.h>`（解决 Serial not declared）；`.ino` 文件不触发 Arduino Core 路由（`_needs_arduino_core` 识别 .ino 扩展名）；宽异常 `except Exception` 吞代码错误（`_citation_check`/`_confidence_check` 改为窄异常）
- **测试基准建设**：创建 50 个 NL 需求的多类别代码模板；建立 reg+ino 双范式测试框架；Agent 反馈循环验证（3 个 Agent Bug 全部通过 FirmForge 错误反馈自我修复）
- **Arduino 官方示例基准测试**：143 个官方示例复制到测试目录，启动全量测试（37/85 运行中，25 通过）
- **单元测试 153 passed**

## 2026-07-21
- **Detect 方案重构**：删除 Boot Signature 注入机制（`board_detector.py` 中 `inject_boot_signature()`/`_boot_gen()`/`_boot_avr_uart0()`/`_scan_serial_signature()` 等 ~250 行代码全部清除（源码污染不合规））；新增 `_infer_from_workspace()`（优先 board.json，其次源码寄存器分析）+ `_infer_from_source()`（mega-only 寄存器区分 328P vs Mega2560）+ `reset_to_bootloader()` 辅助方法；`detect()` 新增 `source_dir` 参数
- **工作区推断不依赖 platformio.ini**：仅分析 board.json 和源码寄存器名（AVR 130+ 标识符）
- **多板检测 Bug 修复**：detect() 收集全部 AVR 探针结果，多板返回候选列表让用户指定
- **detect_port 双阶段策略**：关键词匹配（0ms）→ 仅多板时 avrdude 确认探针（零额外开销）
- **_bootloader_reset 加固**：改用 ComPort（pyserial + Win32Serial fallback），复位等待延时 1.5s
- **E2E 验证**：UNO 21.6s / Mega 30.8s / 双板检测正确
- **单元测试 155 passed**

## 2026-07-22
- **_preprocess_ino 重构**：预处理输出到 `__firmforge_cache__/` 临时目录，不再写回源文件；新增 `c_decl_re`（`void func;`→`void func();` C 风格前向声明转 C++ 格式）；`proto_re` 修复（只匹配 `{` 结尾的函数定义，避免重复注入）
- **源文件保护原则确立**：Arduino 官方例程不可修改，所有转换在内存完成，修复必须是通用规则
- **例程修复效果**：Communication_Graph / SerialCallResponse / SerialCallResponseASCII / RowColumnScanning 从失败变 PASS（c_decl 转换修复）
- **单元测试 155 passed**

## 2026-07-23
- **官方例程库建立**：从 GitHub 建立只读例程库 `~/.firmforge/examples/arduino/builtin/`（81 .ino）和 `~/.firmforge/examples/arduino/avr/`（79 .ino），全部 chmod 444 只读；旧 `vendor/arduino/examples/` 清空
- **Mega2560 官方例程全量编译**：94 例程，90 通过（95.7%），串口例程 8/8 全链路（Review→Build→Flash→Test）通过
- **.ino 预处理器三项修复**：struct 深度感知（C 风格声明转换仅顶层作用域，避免 `byte field2;`→`byte field2();`）；#if 剥离（`strip_preprocessor_blocks()` 移除条件编译块，避免 `class SPISettings` 误扫描）；C 风格收缩（`c_decl_re` 仅 `void name;` 模式，避免 `int knockVal;` 误转）
- **Core 编译增加 .S 汇编支持**：glob 从 `(*.c, *.cpp)` 扩展为 `(*.c, *.cpp, *.S)`，修复 `wiring_pulse.S` 链接
- **Core 编译缓存**：SHA256 哈希 + manifest.json 缓存 Core 编译产物，冷 55s→热 3s（14x 提升），Mega + UNO 双 MCU 独立缓存目录
- **Pre-commit hook**：安装 ruff + pytest 门禁，35 处 lint 全部清零
- **UNO 串口例程 6/6 全链路通过**

## 2026-07-24
- **UNO 全量编译测试完成**：83/89 通过（93.3%），排除 TouchSensorLamp（缺 CapacitiveSensor 库）+ 09.USB
- **UNO 串口全链路**：6/6 通过
- **Ping.ino 误报修复**：SourceReviewer 扫描原始 .ino 文件时注释中 ALL_CAPS 词（GND/PING/SIG）被误判为幻觉寄存器 → Arduino API 代码（.ino 或 `#include <Arduino.h>`）跳过 Register Review，裸寄存器代码仍走 Review
- **单元测试 178 passed**

## 2026-07-25
- **ff_monitor 实时串口面板**：启动独立 Python 子进程读串口，写入含 JS 轮询代码的 HTML（`fetch(?t=timestamp, cache:no-store)` 穿透缓存），非阻断、无闪烁、自动滚底
- **MEMORY.md 全局更新**：整理为 v3.0 B+ 架构（5 个 MCP 工具、5 阶段管道、双编译路线对等、设计决策 13 条、验证记录汇总）
