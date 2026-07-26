# FirmForge 开发计划 — MVP 路线图

> 依据：《多MCU自动化编程智能体-总体规划-v2.4》（项目唯一最高纲领性文件）。
> 本计划为其下游开发管理文档，明确"开发模块 → 优先级 → 步骤"。各模块的接口、数据结构、算法等详细设计，在开发该模块时再单独约定（见规划文档顶部"文档治理声明"）。
> 版本：2026-07-12 | 更新：mvp 完成 + v2.4 分层混合路线 + 范式推断引擎 + Arduino Core 工具链 | 状态：阶段 0-3 ✅ | 阶段 4 🔄 接近收尾
> 命名规范：知识层统一用 `knowledge`（目录）/ `KnowledgeBase`（类名），不再使用 `kb`/`DKB`/`CRKB` 等含 KB 的缩写简称（见规划 §2.6.2）。
> 本次更新：①MVP（阶段 0-3）全部完成并验收；②v2.4 分层混合路线：LLM 代码生成三层架构（规则约束→引用验证→行为验证），知识库角色从"允许列表"→"验证基准"；③Layer 1 范式推断引擎：board.json paradigm 字段 + ParadigmResolver 模块，5 种范式自动推断；④Arduino Core 工具链集成，支持 Arduino API 代码编译。

---

## 一、目标与总原则

**总目标**：先实现 MVP，再渐进式补强。MVP 必须跑通 **FirmForge 7-Stage Pipeline**（规划 §2.9）的"自然语言 → Arduino Mega2560 → 初始化→规划→代码生成→编译→烧录→硬件验证"**全自动闭环**。

**总原则（严守规划 v2.4 既定决策）**：
1. board 顶层架构：代码以电路板为顶层组织单位。
2. vendor 引用复用，不复制芯片库源码。
3. 裸工具链：avr-gcc+avrdude / arm-none-eabi-gcc+openocd，不用 PlatformIO 平台。
4. AHL 退役：不建 `ahl/` 目录，不出现 `ahl_*` 命名；设计原则转"BSP 设计准则"。
5. 封装最小化：Arduino 线不建独立 BSP；STM32 只封静默失败高危项。
6. 分治边界：`providers/base.py` 是必须守住的边界，新增板只填适配层、不改核心框架。
7. AI 成功率优先于跨 MCU 统一。
8. **经验账本**（P0，§2.8.1）：Agent Core 新增 `experience_ledger.py`，跨会话经验积累。
9. **路由型 Skill**（P0，§2.8.1）：Skill Engine 含 `_router.md` 按需分发，避免 Token 浪费。
10. **硬件宪法约束**（P1，§2.8.2）：board.json `constraints` 字段，Codegen 前注入 MCU 物理约束。
11. **三层 Token 优化**（P1，§2.8.2）：常驻→会话→按需 三级上下文加载策略。
12. **7-Stage Pipeline**（P0，§2.9）：端到端工作流 7 阶段。
13. **分层混合代码生成**（P0，§2.10）：Layer 1 范式约束 → Layer 2 Citation Gate → Layer 3 编译/HIL 验证。LLM 自由生成，闸门把关。
14. **范式推断引擎**（P0，§2.11）：Init 阶段自动推断编程范式（arduino/hal/ll/register/esp_idf），CodeGenerator 按范式生成对应风格代码。
15. **知识库 = 验证基准**（v2.4 核心决策）：知识库不限制生成，只验证生成结果。不完整时降级为编译兜底。

---

## 二、MVP 定义与验收标准

**MVP 范围** = 阶段 0 → 阶段 3（见第四节）。交付一个能"听懂人话、自己焊固件"的 Arduino 单线智能体。

**MVP 验收标准（阶段 3 验证点）**：
- [x] **7-Stage §1 Init**：`ff init` 扫描 USB 端口，VID/PID 匹配识别 Arduino Mega2560，自动加载 board.json + knowledge 索引。未匹配时询问用户。
- [x] **7-Stage §2 Plan**：用户输入功能需求 → PlanGenerator 生成 `.firmforge/plan.md` → 用户审查确认或反馈修改 → AI 重生成 → 锁定后进入编码。
- [x] **7-Stage §3-7 全链路**：用户自然语言输入（如"用 Arduino Mega 让 LED 以 2Hz 闪烁"/"串口回显大写"）→ Agent 自动完成 Code→Build→Flash→Test→Verify 全链路。
- [x] 至少覆盖两类任务：**GPIO（blink）** 与 **UART（串口通信）**，证明不只是单点 demo。
- [x] **调度模式自动选择**：单功能点任务（blink/echo）走批处理模式；多功能点任务（如"串口回显+LED心跳"=3 功能点）走模块级流水线模式。
- [x] 错误自修：编译失败进 `compile_fix` 循环（≤3 轮），烧录失败进 `flash_retry`（≤2 次），连续失败转 `give_up` 并报告。**编译修复闭环按 §2.8.1 范式**：解析编译日志→AI修复→重编译验证，失败历史沉淀入经验账本。
- [x] 安全闸：烧录前 `review/safety_check` 门禁必过；关键配置值置信度 < 58% 转人工复核（§2.7 置信度评分，MVP 以最简阈值承接）。**Codegen 前注入 board.json `constraints` 硬件宪法约束，守卫 ISR 禁止阻塞/开漏要求等**。
- [x] CLI 可用：`ff init` / `ff gen <board> "<intent>"` / `ff run <board> --app <dir>` 三条主命令跑通。
- [x] 零工具链烦恼：首次运行自动检测/下载裸工具链到 `~/.firmforge/toolchains/`（产品名作前缀，业界惯例），不污染系统 PATH。

**MVP 明确不做（归 P1/P2）**：完整向量检索 RAG、引用门禁 validator、硬件信号回灌（GDB 回读）、MCP Server、社区资源库、STM32 线、IDE 插件、SSE 流式日志、Per-Agent 模型配置、社区 Playwright 采集。

> ⚠️ **MVP 架构就绪项（阶段 1-3 要做的，区别于"不做"）**：
> - **P0 经验账本**：阶段 1 建 `experience_ledger.py` + `ledger.jsonl`，轻量；不依赖向量检索。
> - **P0 路由型 Skill**：阶段 1 Skill Engine 骨架含 `_router.md` 分发机制；不依赖完整 Skill CI。
> - **P0 7-Stage §1 Init**：阶段 1 建 `board_detector.py`（USB 扫描 + VID/PID 匹配）；不依赖原理图解析（P2）。
> - **P0 7-Stage §2 Plan**：阶段 1 建 `plan_generator.py` + `.plan` 文件协议；不依赖完整 RAG（用 JSON 查表保底）。
> - **P0 7-Stage §3-7 调度**：阶段 3 ToolOrchestrator 实现批处理 + 模块级流水线双模式；不依赖多子 agent（P2）。
> - **P1 硬件宪法约束**：阶段 1 board.json 定型时引入 `constraints` 字段；Codegen 前注入最简单门禁（不依赖 validator 全链路）。
> - **P1 三层 Token 优化**：阶段 1 上下文管理策略就绪；阶段 2 知识库上线后真正发挥效果。
> - **P1 Skill CI 验证**：阶段 2 引入 `validate_skills.py`；不阻塞阶段 1 骨架。
> - **P1 Kconfig 功能裁剪**：阶段 1 board.json 定型时引入 `features` 字段；阶段 3 编译时生效。
> - **P1 多平台版本追踪**：阶段 2 引入 `platform_config.yaml`。

---

## 三、开发模块清单与优先级

按六层架构拆解。优先级含义：**P0 = MVP 核心（阶段 0-3 必须）**；**P1 = 渐进补强（阶段 4+）**；**P2 = 远期扩展（阶段 5/6+）**。

| 层（规划 §2.6） | 模块 | 优先级 | 说明 / 关键约束 |
|---|---|---|---|
| **交互适配层 Adapters** | CLI（`ff` 命令） | **P0** | `ff init`（USB扫描+board识别）/ `ff gen` / `ff run` / `ff flash`，argparse 裸跑 |
| | MCP Server | P1 | stdio(本地)+SSE(远程)，嵌入 CodeBuddy/WorkBuddy |
| | IDE 插件（VS Code） | P2 | MCP Server 的图形壳，阶段 4+ |
| **智能体核心层 Agent Core** | BoardDetector（7-Stage §1） | **P0** | `board_detector.py`：pyserial 枚举 COM + USB VID/PID 查表匹配 board 指纹；未匹配询问用户。原理图扫描归 P2 |
| | PlanGenerator（7-Stage §2） | **P0** | `plan_generator.py`：生成 `.firmforge/plan.md`（功能分解+模块划分+依赖图+调度建议），支持用户审查→重生成迭代 |
| | TaskPlanner | **P0** | 自然语言 → 任务分解（板级语义承接），PlanGenerator 的底层能力 |
| | CodeGenerator | **P0** | 调 LLM 生成应用代码，按 paradigm 生成对应风格（Arduino API / 寄存器 / HAL），7-Stage §3 |
| | ParadigmResolver（范式推断） | **P0** | `paradigm_resolver.py`：Init 阶段自动推断编程范式，四级决策（board.json 显式→用户意图→板子身份+工具链→MCU 默认） |
| | ToolOrchestrator | **P0** | 7-Stage §3-7 流水线编排 + 调度模式自动选择 + Citation Gate + Confidence Gate |
| | AgentStateMachine | **P0** | 错误恢复状态机（§2.5，编译3轮/烧录2次），含 §2.8.1 AI编译修复闭环范式（parse→fix→rebuild→lesson），模块级/项目级双作用域 |
| | SkillEngine | **P0** | 四类 Skill 加载/调度骨架，含 `_router.md` 路由分发（§2.8.1） |
| | ExperienceLedger（经验账本） | **P0** | `experience_ledger.py` + `ledger.jsonl`，错误恢复后自动沉淀 Lesson，下次编译/烧录前注入上下文（§2.8.1） |
| | ContextManager（三层Token优化） | **P1** | 常驻层/会话层/按需层三级加载策略（§2.8.2），阶段 1 就绪，阶段 2 知识库上线后生效 |
| | AgentTrace | P1 | 执行轨迹/工作记忆，MVP 用轻量 JSONL |
| | 多子 agent 并行派发 | P2 | Embedder 借鉴项，MVP 以状态机承接 |
| **知识层 Knowledge** | KnowledgeBase 统一查询接口 | **P0** | 三类来源 `reference\|api\|community` 统一门面 |
| | Arduino API 契约库（最小） | **P0** | `knowledge/api/avr/`，覆盖 pinMode/digitalWrite/串口/UART 等核心 API + usage_examples |
| | board.json（arduino_mega） | **P0** | `schematic_source: manual_entry`，含 `constraints`（硬件宪法约束，§2.8.2）+ `features`（Kconfig 功能裁剪，§2.8.2） |
| | 文档/寄存器参考库（reference） | P1 | JSON 精确查表；AVR 自研 Profile 先覆盖 GPIO/UART |
| | AVR SVD Profile | P1 | 自研，参考 Microchip ATDF |
| | RRF 融合检索 + ChromaDB 向量 | P1 | 双存储分离（JSON+语义），list[ScoredHit] k=60 |
| | 引用门禁 validator | P1 | §2.7：生成值须带 `$ref`，无来源编译前阻断 |
| | 置信度评分 | P1 | §2.7：关键值带置信度，<58% 转人工（safety 承载） |
| | STM32 SVD 导入 | P2 | 阶段 5 用官方 SVD |
| | 社区资源库（community） | P2 | 按板分库采集，forum_qa.verified 结构化 |
| **基础设施层 Infrastructure** | HIL Framework（最简） | **P0** | assert + 串口收集（pyserial），软验证 |
| | 硬件信号回灌 | P1 | §2.7：OpenOCD/GDB 回读寄存器作硬证据 |
| | 逻辑分析仪/功耗仪驱动 | P2 | Saleae 采样，远期 |
| | Skills Repo | **P0** | `skills/` 四类 YAML 骨架（codegen/review/test/verify），含 `_router.md` 路由层 |
| | `validate_skills.py`（Skill CI 验证） | P1 | CI 校验 SKILL.md frontmatter 格式 + 触发条件完整性（§2.8.2），阶段 2 引入 |
| | `platform_config.yaml`（版本追踪） | P1 | 追踪 vendor SDK + 工具链 commit/版本号（§2.8.2），阶段 2 引入 |
| | Tracing Logger | **P0** | JSONL 本地，轻量 |
| **MCU 提供者层 Providers** | `providers/base.py`（分治边界） | **P0** | 接口协议，必须守住 |
| | Arduino BuildProvider | **P0** | 封装 avr-gcc（裸 CLI，路径用 `C:/`） |
| | Arduino FlashProvider | **P0** | 封装 avrdude（含 COM 检测、wiring 协议） |
| | Arduino TestProvider | **P0** | 烧录后验证（串口判读/assert 收集） |
| | STM32 Provider | P1 | arm-none-eabi-gcc + openocd，阶段 5 |
| | 多板 Provider | P2 | ESP32/GD32 等 |
| **代码层 Code** | arduino_mega board.json + apps 模板 | **P0** | 复用现有 blink/serial_echo 工程 |
| | STM32 BSP（bsp_config + BSP 基类） | P1 | 阶段 5；封装最小化只封 RCC/复用/三段式 |
| | 多板扩展 | P2 | 阶段 6+ |

---

## 四、开发步骤（阶段化）

### 阶段 0：Arduino 环境与链路验证 ✅（已完成，2026-07-08/09）
- 裸 avr-gcc 14.1.0 + avrdude 8.1 安装（gh-proxy.com 代理/winget）。
- blink 编译+烧录+LED 闪烁；纯 C 串口程序 4 项测试全 PASS；全流程自动化脚本验证。
- **验证点**：完整闭环跑通 ✅。**本阶段不写 Agent 代码，只验证工具链链路。**

### 阶段 1：框架基座（~4 周，P0）✅（已完成，2026-07-11）
- **目标**：把"骨架"立起来，模块能空跑、接口能串通。
- 关键模块：`board.json` schema 定型（含 `constraints` 硬件宪法约束 + `features` Kconfig 功能裁剪）、`providers/base.py` 接口协议、AgentStateMachine（含 COMPILE_FIX_LOOP 实现范式：parse→fix→rebuild→lesson，模块级/项目级双作用域）、`experience_ledger.py` 经验账本（与 AgentTrace 并列，轻量 JSONL）、SkillEngine 骨架（含 `_router.md` 路由分发）、ContextManager 三层 Token 加载策略（常驻/会话/按需）、目录树（`firmforge/{core,providers,infrastructure,adapters}/` + `knowledge/` + `skills/`）。
- **7-Stage Pipeline §1-2 模块**：`board_detector.py`（USB 扫描 + VID/PID 匹配，MVP 范围）、`plan_generator.py` + `.plan` 文件协议（`<workspace>/.firmforge/plan.md`，draft→reviewed→locked 状态机）、`ff init` 命令骨架。
- 交付物：可初始化的 Agent 框架；`ff init` 能扫描 USB 识别 board；`ff` 命令能解析参数并 dispatch 到空 Provider；经验账本能追加/检索 Lesson；Skill 能按路由分发；PlanGenerator 能生成 plan.md 草案。
- 验证点：框架 import 无错、状态机单测通过、Skill 路由能分发、`experience_ledger.py` 读写单测通过、`board_detector.py` 能识别已知 Arduino 设备、`plan_generator.py` 能输出结构化 plan.md。
- 依赖：无（阶段 0 已完成）。
- **守住**：`providers/base.py` 边界；命名规范 §2.6 全部落实（一个概念一个名字）。

### 阶段 2：知识层（~4 周，P0 最小集）✅（已完成，2026-07-11）
- **目标**：让 CodeGenerator 有"依据"可查，而非纯靠 LLM 记忆。
- 关键模块：KnowledgeBase 统一查询接口、`knowledge/api/avr/api.json`（最小集：GPIO/UART 核心 API + usage_examples）、`boards/arduino_mega/board.json`（manual_entry，含 constraints/features）、参考库最小骨架 + 双存储骨架（JSON 查表先上，ChromaDB 后接）、`infrastructure/platform_config.yaml`（多平台版本追踪，§2.8.2）、`validate_skills.py`（Skill CI 验证流水线，§2.8.2）。
- 交付物：RAG Service 最小可用——给定"让 13 脚 LED 闪"，能查到 `pinMode(LED_BUILTIN, OUTPUT)` 契约与 board.json 的 `led_builtin:13`；`constraints` 约束注入 Codegen 上下文生效；版本追踪文件就绪。
- 验证点：查询接口单测；CodeGenerator 能基于知识库产出 blink 代码骨架；`validate_skills.py` CI 流水线通过。
- 依赖：阶段 1 框架。

### 阶段 3：Provider + Skill + CLI 闭环 = **MVP 验证点**（~4 周，P0）✅（已完成，2026-07-11）
- **目标**：自然语言 → Arduino 全自动闭环跑通（7-Stage Pipeline 全链路）。
- 关键模块：Arduino BuildProvider（avr-gcc 封装）、FlashProvider（avrdude 封装 + COM 检测 + 路径 `C:/`）、TestProvider（串口判读）、四类 Skill 最简实现（codegen/review/test/verify，route 分发确认）、CLI `ff init`/`ff gen`/`ff run`、safety_check 最简门禁（看门狗/HardFault/栈溢出 + 置信度阈值 58% 转人工 + constraints 硬件宪法约束守卫）。**COMPILE_FIX_LOOP 验证**：编译失败自动进 `parse→fix→rebuild` 循环 ≤3 轮，失败历史写入经验账本。**features 功能裁剪生效**：编译时按 features 开关跳过未启用外设。
- **7-Stage Pipeline §3-7 调度逻辑**：ToolOrchestrator 根据 plan.md 功能点数量自动选择调度模式（≤2 批处理 / >2 模块级流水线）；模块级流水线按模块依赖图顺序执行，每模块走 review→compile→flash→test→verify 微流水线；硬件不在线自动降级批处理模式。
- 交付物：用户说"串口回显大写" → `ff run arduino_mega --app apps/echo` 自动生成、编译、烧录、回读串口验证全过（批处理模式）；"串口回显+LED心跳" → 模块级流水线模式（3 功能点 > 2）。
- **验证点（MVP 里程碑）**：GPIO + UART 两类任务自然语言全自动闭环成功（批处理模式）；至少 1 个多功能点任务走模块级流水线闭环成功。
- 依赖：阶段 1 + 阶段 2。
- **通过后启动 STM32 线（阶段 5），可与阶段 4 部分并行。**

### 阶段 4：渐进补强（~4 周，P1）🔄（进入收尾，2026-07-12）
- **目标**：从"能跑"到"可信、好用、可集成"。
- 关键模块：完整 RAG + **引用门禁 validator** + **置信度评分** + LLM 代码生成 + 范式推断引擎 + MCP Server。
- **已完成（2026-07-12）**：
  - ✅ AVR 寄存器参考库 + 引脚映射库
  - ✅ KnowledgeBase RRF 融合搜索（hybrid_search + ScoredHit + k=60）
  - ✅ 引用门禁 Citation Validator + 集成到 7-Stage Pipeline（Code→Build 之间，幻觉寄存器阻断）
  - ✅ 置信度评分 Confidence Scorer + 集成到 Pipeline
  - ✅ CodeGenerator LLM 代码生成（PlanSpec → 综合 prompt → LLM → C 代码）
  - ✅ ParadigmResolver 范式推断引擎（5 种范式，四级决策，board.json paradigm）
  - ✅ Arduino Core 工具链（自动检测 Arduino.h，24 源文件链接，avr-g++ 编译）
  - ✅ E2E 验证：Arduino API 心跳代码全 7 阶段 PASS（17.9s，pinMode/digitalWrite/Serial）
  - ✅ 103 个新测试，262/262 全通过
- **待收尾**：
  - MCP Server 适配器
  - Citation Gate 尾注释处理（代码行尾 `/* ... */` 可能误触发）
  - ChromaDB 向量检索接入（P2，可推迟）

### 阶段 5：STM32 线启动（按板，复用核心框架，P1）
- **目标**：验证"框架复用边界"——核心不动，只填适配层。
- 关键模块：STM32F103VET6 `board.json` + `bsp_config.h`、`vendor/stm32/bsp/<series>/` BSP 基类（封装最小化：RCC/复用/三段式）、STM32 Provider（arm-none-eabi-gcc + openocd）、STM32 SVD 导入、STM32 API 契约库。
- 交付物：自然语言 → STM32 板全自动闭环（blink + 串口）。
- 验证点：STM32 线复用阶段 1-3 核心，仅新增适配层；烧录验证（注：当前 STM32 烧录因 AN3155 时序异常暂停，本阶段需先攻克）。
- 依赖：阶段 3 验证点通过（规划 R11 强制）。

### 阶段 6+：多板 / 多 MCU 扩展（P2）
- ESP32 / GD32 / STM32F4-H7 / STC8H（按规划推后至阶段 6+）。
- 原理图 ingestion（`kicad_netlist` 自动生成 board.json，§2.7 / §3.1.3）。
- Vision 物理验证（摄像头帧差确认 LED 闪烁，人工关自动化）。
- IDE 插件图形壳。

---

## 五、优先级决策依据（为什么这么排）

1. **P0 只保留 MVP 闭环最小必要集**：任何"增强可信度/可扩展性"的能力，只要 MVP 能用简化方式承接，就降为 P1。例如置信度评分 MVP 只做"阈值 58% 转人工"最简版，完整置信度模型归 P1。
2. **§2.7 四项借鉴的分流**：
   - 引用门禁、置信度评分、硬件信号回灌 → MVP 以"最简熔断"（safety_check + 串口判读）承接，**完整机制归 P1**（阶段 4）。
   - 原理图 ingestion → board.json 的 `manual_entry` 即 MVP 形态，自动化解析归 P2。
3. **§2.8 竞品借鉴的分流**：
   - **P0 经验账本**：轻量（JSONL 追加），不依赖 RAG，阶段 1 即可实现；解决跨会话经验积累空白——价值高+成本低。
   - **P0 路由型 Skill**：`_router.md` 仅需分发逻辑，不依赖 Skill CI 验证；补上 Token 浪费的核心问题。
   - **P1 硬件宪法约束**：board.json 定型时顺手引入 `constraints` 字段，Codegen 前注入最简单门禁——成本低但有实效。
   - **P1 三层 Token 优化**：阶段 1 策略就绪，阶段 2 知识库上线后真正发挥效果。
   - **P1 Skill CI 验证**：`validate_skills.py` 需 CI 流水线，阶段 2 引入，不阻塞阶段 1 Skill 骨架。
   - **P1 Kconfig 功能裁剪**：board.json 定型时顺手引入 `features` 字段，阶段 3 编译时生效。
   - **P1 多平台版本追踪**：`platform_config.yaml` 轻量，阶段 2 工具链管理引入，补充 v2.1 版本锚定的分发侧一致性。
   - **P2/P3 项**：USB-TTL 检测归 FlashProvider（阶段 3 实现时加入）、SSE/Per-Agent/Playwright 等后续按需。
4. **封装最小化直接砍掉 Arduino BSP**：Arduino 原厂 variant 已 AI 友好，按 R6 不建独立 BSP，故 P0 代码层无 BSP 模块；STM32 BSP 归 P1（阶段 5）。
5. **MCP Server / IDE 插件不在 MVP**：CLI 已能证明闭环价值，MCP 是"集成形态"而非"能力形态"，归 P1/P2。
6. **AgentTrace / 多子 agent 并行后置**：现有状态机（编译3轮/烧录2次/反思步）足以承接错误自修，多子 agent 是 Embedder 前瞻能力，归 P2。
7. **7-Stage Pipeline 的 MVP 范围**（§2.9）：
   - **§1 Init 进 MVP**：USB 扫描 + VID/PID 匹配（产品级可用），原理图扫描归 P2。BoardDetector 轻量（pyserial + 查表），不依赖 RAG。
   - **§2 Plan 进 MVP**：`.plan` 文件交互（draft→reviewed→locked），PlanGenerator 调用 knowledge + constraints 生成规划。用户审查是"人在环"的必要环节，不可省略。
   - **§3-7 全链路进 MVP**：批处理模式 + 模块级流水线模式均实现，由 ToolOrchestrator 按功能点阈值自动选择。
   - **调度阈值 2 的依据**：blink/serial_echo 等单外设任务通常 1-2 功能点，适合批处理；多外设组合（如 UART+LED+PWM）通常 3+ 功能点，需要模块级精确验收。阈值可配（`ff config --threshold N`）。

---

## 六、关键依赖与风险（复用规划 §七 + 实战）

| 风险/依赖 | 等级 | 应对（开发计划视角） |
|---|---|---|
| 工具链下载体验（GitHub 不可达） | 中 | 阶段 1 即落实 bootstrap + 国内镜像/gh-proxy 兜底；不依赖 GitHub 直连 |
| 型号级分治边界失守 | 🟠 中 | 阶段 1 锁死 `providers/base.py`；STM32 线只填适配层 |
| STM32 烧录时序（AN3155 异常） | 🟠 中 | 阶段 5 前置攻克（当前暂停），优先用 ST-Link+openocd 而非 USB-TTL 协议 |
| AVR SVD 自研工作量 | 中 | 阶段 4 做，参考 Microchip ATDF，先覆盖 GPIO/UART |
| 知识库查询准确性 | 中 | 阶段 2 先 JSON 精确查表保底，向量检索阶段 4 补强 |
| 置信度阈值合理性 | 低 | 58% 为初始值，阶段 4 用 Benchmark 校准 |
| 经验账本冷启动（无历史 Lesson） | 低 | 阶段 1 预留结构，阶段 3 编译修复闭环实战中自然积累 |
| constraints 约束覆盖不全 | 低 | MVP 先覆盖已知高危（ISR 禁止阻塞/I2C 必须开漏），随着实战补充 |
| USB VID/PID 覆盖不全（7-Stage §1） | 中 | MVP 先覆盖已知 Arduino/ST-Link，未匹配时询问用户；逐步扩充指纹库 |
| 模块级流水线烧录次数多（7-Stage §3） | 中 | 硬件不在线自动降级批处理；功能点阈值可调；MVP 验证用简单多模块任务 |
| .plan 用户迭代体验（7-Stage §2） | 低 | Markdown 可读性好，CLI 辅助提示审查要点 |

---

## 七、里程碑估算（保守）

| 里程碑 | 对应阶段 | 累计周数（估） |
|---|---|---|
| 链路验证 ✅ | 0 | 已完成 |
| 框架基座 ✅ | 1 | 已完成 |
| 知识层最小集 ✅ | 2 | 已完成 |
| **MVP 闭环（验证点）** ✅ | **3** | **已完成** |
| 渐进补强 🔄 | 4 | 进入收尾（7/10 已完成） |
| STM32 线 | 5 | ~8 周 |
| 多板扩展 | 6+ | 持续 |

> 注：周数为规划文档阶段估算的累加，实际以迭代节奏为准；阶段 3 是第一个可交付用户的里程碑，应力保。

---

## 八、与规划文档的关系

- 本计划是规划 v2.4 的**下游开发管理文档**，不新增架构决策，仅将既定决策翻译为"模块+优先级+步骤"。
- 若本计划与规划文档冲突，**以规划文档为准**。
- 各模块详细设计（接口/数据结构/算法）按治理声明，在开发该模块时再约定，不前置固化。
- **v2.4 新增**：分层混合路线（§2.10）+ 范式推断引擎（§2.11）+ ParadigmResolver 模块 + Arduino Core 工具链。
