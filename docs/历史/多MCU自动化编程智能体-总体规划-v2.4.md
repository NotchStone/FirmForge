# 多MCU自动化编程智能体 — 总体规划 v2.4（产品名：FirmForge / 命令行 ff）

> 版本：v2.4 | 日期：2026-07-08 | 更新：2026-07-12（LLM 代码生成分层混合路线 + Layer 1 范式推断引擎 + Arduino Core 工具链）| 状态：MVP（阶段 0-3）完成，阶段 4 渐进补强接近收尾
>
> **🏷️ 产品命名（v2.3 锁定，v2.4 确认保留）**：英文 **FirmForge** = Firmware + Forge（铁匠铺/锻炉之喻，隐喻"将自然语言锻造成运行中的固件"，涵盖全链路而非仅烧录环节），命令行 `ff`，Python 包 `firmforge`，中文名 "**锻芯**"（锻=forge，芯=chip/firmware，两字干净）。
>
> **v2.4 相对 v2.3 的关键变更**：
> - **LLM 代码生成分层混合路线（§2.10）**：确立三层架构——Layer 1 规则约束（软约束，范式驱动）→ Layer 2 引用验证（硬闸门，Citation Gate）→ Layer 3 行为验证（编译+HIL），替代 v2.3 "只使用原厂库函数"的硬约束思路。知识库角色从"允许列表"变更为"验证基准"。
> - **Layer 1 范式推断引擎（§2.11）**：board.json `paradigm` 字段 + Init 阶段自动推断。支持 arduino / hal / ll / register / esp_idf 五种编程范式，根据板子身份、MCU 系列、用户意图关键词、工具链可用性四级决策。LLM 按推断范式生成对应风格代码（Arduino API / 寄存器 / HAL 库等）。
> - **Arduino Core 工具链集成**：BuildProvider 自动检测 `#include <Arduino.h>`，链接 Arduino AVR Core（24 源文件），avr-g++ 编译 C++ 类。寄存器级代码仍用 avr-gcc 单步编译，向后兼容。
>
> **v2.3 相对 v2.2 的关键变更（保留）**：
> - **AHL 退役**：AHL 作为代码层名字完全下线，后期不再使用。设计原则转为"BSP 设计准则"。
> - **board 顶层架构**：以电路板为代码组织顶层单位，vendor 芯片系列库被引用复用不复制。
> - **裸工具链**：不用 PlatformIO 平台，Provider 直接调用裸工具 CLI。
> - **Arduino 优先单线**：首发 Arduino Mega2560，STM32 推后至验证点通过后启动。
>
> 📜 **文档治理声明（最高纲领）**：本规划文档（v2.4）是 FirmForge 项目**唯一最高纲领性文件**。所有架构、命名、模块归属、关键决策以本文为准。前期文档已统一移入 `docs/历史/` 目录，仅作历史参考。各模块的详细设计（接口、数据结构、算法）在开发时再单独约定，不前置固化。
>
> 关联文档（非准则）：`docs/历史/`（前期文档）、`docs/技术路线分析-LLM代码生成约束策略.md`（路线选型论证）、`docs/Layer1-范式选择规则规范.md`（Layer 1 规则规范）、`.workbuddy/PROJECT_RULES.md`、`.workbuddy/skills/SKILLS.md`

---

## 一、演进背景与方向调整

### 1.1 评审结论回顾

前序评审得出综合评分 63/100 → 86/100（v2.0），核心问题与应对：

| 问题 | 严重度 | 应对 |
|------|-------|------|
| SDCC+STC8H 兼容性未验证（致命） | 🔴 | 放弃 SDCC，改用 Arduino+STM32 成熟工具链 |
| STC8H 市场覆盖面窄 | 🟠 | STC8H 降级为后期扩展 |
| RAG 对嵌入式手册表格向量化效果差 | 🟠 | 知识库协议 P0/P1 改进（SVD + 结构化存储） |
| 多 MCU 承诺短期无法兑现 | 🟠 | Arduino 优先单线，验证后扩展 |
| 融合 HAL 不切实际 | 🟠 | v2.3 放弃 AHL 跨 MCU 统一，改 board+vendor 分治 |

### 1.2 v2.3 方向调整的核心理由

经多轮深度论证（Arduino AHL 必要性 → STM32 AHL 必要性 → BSP 替代 → board 顶层），认识到：

1. **Arduino API 已是 AI 友好范本**：`pinMode/digitalWrite` 命名直观、GitHub 百万级语料。再封装一层 AHL 会破坏 RAG 语料优势——净价值为负。Arduino 线不做封装层，直接用 Arduino API + variant。
2. **STM32 HAL 对 AI 不友好（4.7/10）**：隐式 RCC、三段式 Init-Use、复用映射是 AI 重灾区。但通过 BSP 层（板级引脚配置 + 复用映射）+ 程序化强制的初始化模板 + 自检，可不引入独立 AHL 封装层解决静默失败。
3. **自然语言编程的载体是具体电路板**：用户说"让板上的 LED 闪烁"是板级语义。以 board 为代码组织顶层单位，最贴合用户认知与物理实体。
4. **原厂代码库分类不同**：Arduino 按 board（variants/），STM32 按 chip series（HAL/）。board 顶层 + vendor 引用复用，各自对齐原厂，代码复用最大化。

### 1.3 v2.3 核心目标

设计端到端自动化编程智能体，用户以自然语言描述需求（含板级信息），智能体按 **FirmForge 7-Stage Pipeline**（§2.9）自动完成**初始化 → 规划 → 代码生成 → 编译 → 烧录 → 硬件在环测试 → 验证**的完整闭环。Init 阶段自动推断编程范式（§2.11），CodeGenerator 按范式生成对应风格的代码（Arduino API / 寄存器 / HAL 库），经分层验证闸门（§2.10）后烧录到硬件。**首发 Arduino Mega2560 单线**，验证点通过后启动 STM32F103 线，后期按板子扩展。

采用 **"board 顶层 + vendor 复用 + Agent 核心框架"** 架构，重点打造四大支柱：
1. **板级支持（BSP + board.json）**：板级语义承接，板级知识集中管理
2. **芯片 RAG 知识库**（应用知识库协议 P0/P1 改进）
3. **社区技术资料知识库**（按板子分库采集）
4. **AI 编码、审查、测试、验证 Skill**（四类 Skill 体系，框架级复用）

> **核心取向**：不为大一统平台强行融合更多 MCU。怎么有利于 AI 自然语言编程的正确率和成功率，是最高优先级。

---

## 二、核心架构

### 2.1 架构概览

```
┌──────────────────────────────────────────────────┐
│  用户自然语言（含板级信息："用 Arduino Mega 点灯"）  │
├──────────────────────────────────────────────────┤
│  Agent 核心框架（型号无关，复用）                    │
│  TaskPlanner → CodeGenerator → ToolOrchestrator   │
│  + Skill Engine + 错误恢复状态机 + RAG Service     │
├──────────────────────────────────────────────────┤
│  board 层（顶层组织单位，按电路板）                  │
│  boards/<board>/ { board.json, bsp_config, apps } │
├──────────────────────────────────────────────────┤
│  vendor 层（芯片系列库，被引用复用，不复制）          │
│  vendor/arduino/ (core+variants)                  │
│  vendor/stm32/ (HAL + CMSIS + BSP基类)            │
├──────────────────────────────────────────────────┤
│  工具链（裸 CLI，免费无授权）                        │
│  avr-gcc + avrdude  |  arm-none-eabi-gcc + openocd│
└──────────────────────────────────────────────────┘
```

### 2.2 六层架构（沿用 v1.0，board/vendor 替代原 ahl 层）

```
交互适配层 (Adapters)       CLI(ff init/gen/run/flash) | MCP Server | VS Code Ext
智能体核心层 (Agent Core)   BoardDetector → ParadigmResolver → PlanGenerator → CodeGenerator → ToolOrchestrator + Skill Engine + Agent Trace + Experience Ledger + ContextManager
知识层 (Knowledge)          RAG Service (手册+板级+社区) — 命名见 §2.6
基础设施层 (Infrastructure) HIL Framework | Skills Repo | Tracing Logger
MCU 提供者层 (Providers)    BuildProvider | FlashProvider | TestProvider
代码层 (Code)               apps/ → boards/<board>/ + vendor/ → 原厂库 → 寄存器
```
> 注：原"记忆/知识层 (Memory)"拆分为「知识层（RAG 知识库）」+「Agent Trace（归入智能体核心层）」，避免"记忆/知识"混用；原"公共设施层 (Facilities)"更名为"基础设施层 (Infrastructure)"，与目录 `infrastructure/` 一致。

### 2.3 调用链约束

```
Arduino: apps/ → boards/arduino_mega/ + vendor/arduino/ → AVR 寄存器
         paradigm=arduino → LLM 生成 pinMode/digitalWrite/Serial（Arduino API）
         paradigm=register → LLM 生成 DDRB/PORTB/UCSR0B（裸寄存器）
STM32:   apps/ → boards/stm32f103vet6_minisys/ + vendor/stm32/ → HAL → 寄存器
         paradigm=hal → LLM 生成 HAL_GPIO_WritePin（HAL 库）
         paradigm=register → LLM 生成 GPIOA->BSRR（裸寄存器）
```

> 约束：AI 生成的应用代码在对应范式下调用对应层级的 API。范式由 Init 阶段的 `ParadigmResolver` 自动推断（详见 §2.11），板级 `board.json` 的 `paradigm` 字段可显式覆盖。Citation Gate（§2.10 Layer 2）根据范式调整校验策略——arduino 范式校验 API 函数名，register 范式强制校验寄存器名。

### 2.4 BSP 设计准则（原 AHL 设计原则转化）

AHL 作为代码层名字退役，但其设计原则转化为"BSP 设计准则"，指导 BSP 与 board.json 的构建：

1. **三层防护**：编译期能挡的不留运行时，运行时挡不了的交给 HIL，HIL 挡不了的交给人工 review。
2. **AI 难以犯错**：板级 API 与初始化模板应让 LLM 忘记参数时在编译期或生成期报错，而非烧录后炸芯片。
3. **RAG 友好**：板级 API 命名直观 + usage_examples 充实；优先复用原厂 API 语料，不发明新 API 破坏语料。
4. **安全分级**：配置类 API `safety_level: strict`，热路径 API `safety_level: fast_path`。
5. **编译期非唯一**：当编译期防护与性能/RAG 友好冲突时，按 API 分类决策。
6. **变长参数安全**：批量调用用哨兵宏替代 count 参数。
7. **封装最小化准则**（v2.3 新增）：只封装"静默失败高危项"（RCC/复用/三段式），参数透传原厂枚举，不重新发明 API。每多封装一层，必须有"它防住了哪类静默失败"的明确理由。

### 2.5 错误恢复状态机

```python
class AgentStateMachine:
    NORMAL_FLOW = "normal"           # 正常流程
    COMPILE_FIX_LOOP = "compile_fix" # 编译错误修复循环（max 3 轮）
    FLASH_RETRY = "flash_retry"      # 烧录重试（max 2 次）
    TEST_DIAGNOSE = "test_diagnose"  # 测试失败诊断
    GIVE_UP = "give_up"              # 超时放弃（连续 N 次失败后）
```

> 状态机在 7-Stage Pipeline 中有两个作用域（§2.9.4）：
> - **模块级**（阶段 3 微流水线内）：单模块的 compile→flash→test 失败修复，错误范围限于当前模块
> - **项目级**（阶段 4-6 宏流水线）：整体编译/下载/测试失败修复，错误范围按"编译日志→模块映射 + 模块依赖图"共同定位

**COMPILE_FIX_LOOP 实现范式**（借鉴 keil-c51-ai-mcu-platform，§2.8.1）：
1. `parse_build_errors(log)` — 从编译日志提取结构化错误（文件/行号/错误类型/消息）
2. `ai_fix_with_context(errors, source_code)` — 将错误+源码喂给 LLM 修复（注入经验账本中相似历史 Lesson 作上下文）
3. `rebuild_and_verify()` — 重编译并验证修复结果
4. 循环三轮仍失败 → `GIVE_UP`，沉淀为经验账本 Lesson

### 2.6 命名规范（v2.3 锁定，开发起步前定稿）

为避免开发启动后大规模重命名，现就各层、目录、模块、知识库子库统一命名。**核心原则：一个概念只有一个名字**。

#### 2.6.1 六层名称（中英文固定）

| 层 | 英文名 | 目录（Python 包） | 说明 |
|----|--------|------------------|------|
| 交互适配层 | Adapters | `firmforge/adapters/` | CLI / MCP / IDE 插件 |
| 智能体核心层 | Agent Core | `firmforge/core/` | 编排 + Skill 引擎 + Agent Trace |
| 知识层 | Knowledge | `firmforge/knowledge/` | RAG 知识库（非 Agent 记忆） |
| 基础设施层 | Infrastructure | `firmforge/infrastructure/` | HIL / Skills Repo / Tracing |
| MCU 提供者层 | Providers | `firmforge/providers/` | Build / Flash / Test |
| 代码层 | Code | `boards/` + `vendor/` | 生成代码与原厂库 |

> **"记忆"与"知识"严格分离**：Agent Trace（执行轨迹/工作记忆，短生命周期）归入 Agent Core；RAG 知识库（长生命周期结构化知识）归入知识层。两者不再共用 "Memory" 一词。

#### 2.6.2 知识库命名——解决 `kb` 费解问题

原文档中"知识库"被四个名字混用：**层叫 Memory、目录叫 `memory/`、Python 包叫 `firmforge.kb`、子库后缀 `_kb`**，且 `_kb` 易与"千字节"混淆。统一为：

| 概念 | 旧名（混乱） | 新名（统一） |
|------|------------|------------|
| 知识库顶层目录 | `memory/` | **`knowledge/`** |
| Python 包 | `firmforge.kb` | **`firmforge.knowledge`** |
| 文档/寄存器参考库 (DKB) | `doc_kb/` | **`knowledge/reference/`** |
| 芯片 API 契约库（原 AHL Code KB） | `ahl_kb/` | **`knowledge/api/`** |
| 社区资源库 (CRKB) | `community_kb/` | **`knowledge/community/`** |
| 向量索引 | `chroma_db/` | **`knowledge/vectors/`** |
| 统一查询接口 | `KnowledgeBase` | `KnowledgeBase`（保留，命名良好） |
| 来源枚举 | `doc_kb\|ahl_kb\|community_kb` | **`reference\|api\|community`** |
| API 契约文件 | `ahl_api.json` | **`knowledge/api/<chip>/api.json`** |

> ⚠️ **AHL 残留已随历史文档封存**：原 `ahl_kb`/`ahl_api.json`/`ahl_gpio_set_mode`/`AHL 代码知识库` 等命名出自已移入 `docs/历史/` 的《知识库协议接口定义》。该文档不再作为开发准则，其 AHL 命名一并作废。AHL 退役后，芯片 API 契约库存放的是**原厂 API 契约**（`pinMode`/`digitalWrite` 或 `HAL_GPIO_*`），本规划统一命名为 `knowledge/api/`，详见 §2.6.3。

#### 2.6.3 历史文档处置（已封存，非待办）

原 `docs/知识库协议接口定义.md` 及其评审报告已整体移入 `docs/历史/`，不再作为开发准则，故无需在活动代码库中执行改名。**其中已吸收的 P0/P1/P2 改进项（SVD 映射、RRF 融合、强类型引用等）已固化为 §3.2 的内容，以本文为准**；其余 AHL 相关表述一律作废。新模块开发时若需查阅，仅作历史参考，不得照抄 `ahl_*` 命名。

#### 2.6.4 文件格式约定（2026-07-11 新增）

FirmForge 涉及多种文件格式。按用途 → 格式的映射关系，遵循四条原则：

> **原则**：可编辑性 > 可读性 > 可解析性 > 可流式写入（优先级依次降低）。
> 人类手动编辑的文件用 MD/YAML；机器消费的结构化数据用 JSON；流式追加的场景用 JSONL。

**A 类：人类编辑优先 → Markdown + YAML frontmatter**

| 文件 | 格式 | 编辑方 | 消费方 |
|------|------|--------|--------|
| `plan.md`（§2.9.3） | MD + YAML frontmatter | 用户（编辑器） | PlanGenerator / AI |
| `SKILL.md`（§3.4） | MD + YAML frontmatter | Skill 作者 | SkillEngine / _router |
| `_router.md`（§3.4） | MD table | Skill 作者 | SkillEngine / _router |
| `*.md`（docs） | Markdown | 人类 | 人类 / GitHub |

> 选型理由：Plan 和 Skill 的主体内容为自然语言叙述（功能分解、测试策略），Markdown 天然适合。元数据（plan_id / board / status）用 YAML frontmatter 锁定结构。不选纯 YAML 因为深层嵌套可读性差、缩进敏感易出错。不选 JSON 因为多行长文本串在 JSON 里体验糟糕。

**B 类：机器读写优先 → JSON（带 Schema 校验）**

| 文件 | 格式 | 编辑方 | 消费方 |
|------|------|--------|--------|
| `board.json`（§3.1.3） | JSON | 开发者 / AI | BoardDetector / CodeGenerator |
| `knowledge/api/<chip>/api.json`（§3.2） | JSON | AI 提取（Doxygen+AST） | KnowledgeBase / CodeGenerator |
| `knowledge/reference/<chip>/*.json`（§3.2.3） | JSON | AI 导入 | KnowledgeBase |

> 选型理由：board.json 有嵌套结构（constraints / peripheral_rules），YAML 缩进层级一多就出错。JSON 有 JSON Schema 2020-12（规划 P1-2）做编译期校验，任何 IDE 都能验证。JSON 是 AI 生成结构化数据最不容易出错的格式（没有缩进歧义）。不选 YAML——缩进错误在 YAML 中不报语法错但语义全变。

**C 类：流式追加 → JSONL（每行独立 JSON）**

| 文件 | 格式 | 写入方 | 读取方 |
|------|------|--------|--------|
| `ledger.jsonl`（§2.8.1 经验账本） | JSONL | ExperienceLedger | ExperienceLedger.search() |
| `trace_*.jsonl`（Agent Trace） | JSONL | TracingLogger | 调试 / 分析工具 |
| `sm_trace_*.jsonl`（状态机轨迹） | JSONL | AgentStateMachine | 调试 / 分析工具 |

> 选型理由：(a) 追加不需要重写整个文件——`open(path, "a")` 即用；(b) 每行是合法 JSON，`tail -f ledger.jsonl` 可实时监控；(c) 损坏一行不影响其余行（完整 JSON 文件一个语法错误全崩）；(d) 按行扫描的线性搜索对 MVP 够用，阶段 4 升级向量检索。不选 SQLite——不需要 SQL 的查询能力且增加依赖。不选完整 JSON——追加需要读→合并→重写，写入成本随文件线性增长。

**D 类：仅扁平单层结构时 → YAML**

| 文件 | 格式 | 理由 |
|------|------|------|
| `platform_config.yaml`（§4.2） | YAML | 扁平键值对，仅一层嵌套，人经常手动改版本号 |

> YAML 仅限"单层、扁平、人类频繁手动修改版本号"的场景。嵌套超过两级的任何内容不进 YAML。

**对照：各格式在项目中的边界**

| 问自己 | 答案 → 格式 |
|--------|-----------|
| 需要人类反复编辑？ | 是 → MD(+frontmatter) 或 YAML |
| 机器生成、机器消费？ | 是 → JSON（+Schema） |
| 需要追加写入、不可丢失旧数据？ | 是 → JSONL |
| 嵌套结构超过两级？ | 是 → 排除 YAML |
| 需要跨语言消费（C/JS/Rust）？ | 是 → JSON 或 JSONL |

---

### 2.7 竞品 Embedder 借鉴与架构融合（v2.3 新增）

对标产品 **Embedder**（embedder.com，2026-04 发布的 AI firmware agent）最值得借鉴的四项能力，已作为架构级设计决策吸收，分别归属 **validator / safety / HIL / board.json** 四个模块。各模块的具体接口与算法在开发该模块时再详细约定（见顶部文档治理声明）。

| 借鉴机制（Embedder） | 归属模块 | 融合后的设计决策（规划级） | 预期效果 |
|---|---|---|---|
| 引用门禁 Citation Gate（无来源的值阻断） | **validator**（代码生成→编译之间的校验闸门，属 review/verify 流水线） | 生成的寄存器 / 位域 / 时钟值必须带 `$ref` 指向知识库 SVD 或参考库条目；无引用来源的值在编译前被 validator 阻断。对齐 §3.2.1 的 P1-4 强类型引用 `{register, field, value} + $ref`。 | 消除"幻觉寄存器 / 错误时钟树"，从源头挡住无依据的写值 |
| 置信度评分 Confidence Scoring（低于阈值转人工） | **safety**（安全加固 Skill + 三层防护人工关） | 生成的关键配置值（引脚复用、时钟分频、电源域）附带置信度评分；低于阈值（默认 58%）自动升级为人工复核，复用 safety 的 human-in-the-loop 闸门（§2.4 三层防护第 3 关）。 | 不确定时不自动烧录，把风险转交人判断 |
| 硬件信号回灌闭环 Hardware Interaction（逻辑分析仪 / 示波器 / GDB 寄存器回读作硬证据） | **HIL**（基础设施层 HIL Framework） | 在现有 assert + 串口收集之外，新增"运行时硬件信号回读"验证通道：优先支持 OpenOCD/GDB 回读外设寄存器值、Saleae 逻辑分析仪采样，将"运行时读回值 vs 预期"作为 verify 阶段的硬证据，而非仅依赖串口文本判读。 | 从"软验证"升级到"硬验证"，闭环证据更可信 |
| 原理图 ingestion（读 KiCad/Altium 网表自动解析引脚布线） | **board.json**（板级支持，§3.1） | 新增 `schematic_source` 的自动化来源：解析 KiCad `.kicad_sch` / 网表导出，自动生成 board.json 的 `pins` 字段（含复用映射、Errata 变通），减少人工录入错误；MVP 阶段仍以人工录入为主，自动化 ingestion 为增量能力。 | 直接服务"AI 难以犯错"准则，降低板级配置错配 |

> 暂未强制纳入 MVP 的能力（作为后期可选项）：Embedder 的"多子 agent 并行派发"（v2.3 以现有状态机编译 3 轮 / 烧录 2 次 / 反思步承接）、"Vision 物理验证（摄像头确认 LED 闪烁）"（以人工关承接）。

### 2.8 竞品工程实践借鉴与融合（v2.3 新增，2026-07-11）

> 来源：6 个 GitHub 开源仓库横向对比分析（`docs/历史/竞品对比分析-6仓库横向对比.md`，原含 TuyaOpen 追加分析），筛选出 14 项可借鉴技术。此处仅记录 P0/P1 优先项（已融入本规划对应章节），P2/P3 项见 §2.8.3 设计预留。

#### 2.8.1 P0 核心借鉴（融入架构，阶段 1-3 实现）

| 借鉴项 | 来源 | 融入点 | 设计决策 |
|--------|------|--------|---------|
| **经验账本** Experience Ledger | Claude-Agent-MCU（C） | Agent Core 新增 `experience_ledger.py`（与 Agent Trace 并列，分治短/长生命周期记忆） | 每次错误恢复后自动提取 Lesson→追加 ledger.jsonl；下次编译/烧录前 Grep 相似历史经验注入上下文。解决 Agent Trace 仅跨步骤、不跨会话的局限。与 v2.1 知识保鲜机制互补（保鲜管结构一致性，账本管工程经验积累）。 |
| **路由型 Skill** | aix-skills（B） | Skill Engine 新增 `_router.md` 路由层（§3.4） | 四类 Skill 内部按外设/审查类型/测试模式分子技能，由路由 Skill 按需分发，避免全量加载到上下文浪费 Token。与三层 Token 优化（§2.8.2）联动。 |
| **AI 编译修复闭环** | keil-c51（E） | 状态机 `COMPILE_FIX_LOOP` 详细实现范式（§2.5） | 编译失败→`parse_build_errors(log)` 提取结构化错误→`ai_fix_with_context(errors, source)`→`rebuild_and_verify()` 重编译验证。误差 3 轮，与经验账本联动（失败历史作为 Lesson 沉淀）。 |

#### 2.8.2 P1 增强借鉴（融入对应模块，阶段 1-2 实现）

| 借鉴项 | 来源 | 融入点 | 设计决策 |
|--------|------|--------|---------|
| **硬件宪法约束注入** | Claude-Agent-MCU（C） | board.json 新增 `constraints` 字段（§3.1.3），Codegen Skill 注入 | 将 MCU 物理约束（ISR 禁止阻塞/I2C 必须开漏/特定引脚规避）声明于 board.json，Codegen 前作为系统提示注入。对齐 BSP 设计准则第 2 条"AI 难以犯错"。 |
| **三层 Token 优化加载** | Claude-Agent-MCU（C） | Agent Core 上下文管理策略（§2.2） | 常驻层（Agent 角色+当前任务+board.json 摘要）、会话层（BSP 准则+constraints）、按需层（API 契约/寄存器手册/社区经验）分级加载。与路由型 Skill 的按需分发联动。 |
| **Skill CI 验证机制** | aix-skills（B） | Skills Repo（基础设施层）质量保证 | `validate_skills.py` 校验 SKILL.md frontmatter 格式 + 触发条件完整性 + 示例可执行性；CI 流水线自动运行。确保 Skill 写错不导致 AI 生成错误代码。 |
| **Kconfig 功能裁剪** | tuyaopen（F，TuyaOpen） | board.json 新增 `features` 字段（§3.1.3） | 借鉴 Linux Kconfig + TuyaOpen `default.config` 机制：声明式功能级开关（外设/协议/特性），板级预设可覆盖。对齐 BSP 设计准则第 7 条"封装最小化"——不用的特性不生成相关代码。 |
| **多平台版本追踪** | tuyaopen（F，TuyaOpen） | 工具链分发（§4.2） | `platform_config.yaml` 追踪各 vendor SDK + 工具链的 commit/版本，确保平台层版本一致性。补充 v2.1 版本锚定机制（编译期 `_Static_assert` 校验运行时版本，此处管分发版本一致性）。 |

#### 2.8.3 P2/P3 设计预留

以下项已评估，暂不入 MVP 需求，在对应模块开发时做设计预留：

| 借鉴项 | 来源 | 预留模块 | 触发条件 |
|--------|------|---------|---------|
| USB-TTL 适配器自动检测 | keil-c51（E） | FlashProvider | 阶段 3 实现 FlashProvider 时加入，pyserial 枚举 + USB VID/PID 识别 |
| 四层 HAL 分层参考（TKL/TAL/TDL/TDD） | tuyaopen（F） | vendor/stm32 BSP 内部分层 | 阶段 5 STM32 线启动时参考，BSP 基类按内核抽象→功能抽象→设备类分层 |
| SSE 流式构建日志 | keil-c51（E） | MCP 适配器 / IDE 插件 | 阶段 4+ 有 Web UI 需求时启用 |
| Per-Agent 模型配置 | oh-my-renesas（D） | Agent Core 配置管理 | 阶段 5+ 多 MCU 扩展后按需启用 |
| 社区 Playwright 采集 | oh-my-renesas（D） | community 采集工具 | 阶段 4 社区知识库建设时作为自动化采集补充 |

> **TuyaOpen 特殊声明**：TuyaOpen（涂鸦智能 AI+IoT 运行时框架，427 commits 企业级）与 FirmForge **赛道不同**（设备端 AI 运行时 vs 主机端代码生成），但其 boards/ 顶层设计验证了 FirmForge 架构方向正确，其 TDD/TDL/TAL/TKL 四层 HAL 为 STM32 BSP 内部分层提供了经过生产验证的参考范式，其 MCP 设备端支持与 FirmForge MCP 适配器方向互补（未来可对接）。

### 2.9 FirmForge 7-Stage Pipeline（端到端工作流，2026-07-11 新增）

> 7-Stage Pipeline 是 FirmForge 的**用户视角端到端工作流**，与 §2.2 六层架构（系统内部视图）互为表里：六层架构回答"系统由哪些部件组成"，7-Stage Pipeline 回答"用户看到什么流程"。所有 Adapters（CLI/MCP/IDE）的交互设计以此为最高流程准则。

#### 2.9.1 七阶段定义

```
┌──────────────────────────────────────────────────────────────────────────┐
│ 1.Init │ 2.Plan │ 3.Code(模块级微流水线) │ 4.Build │ 5.Flash │ 6.Test │ 7.Verify │
│ 初始化  │ 规划   │ 写→审→编→载→测→验     │ 整体编译 │ 整体下载 │ 整体测试 │ 项目验证  │
└──────────────────────────────────────────────────────────────────────────┘
                              ↑                                       │
                              └──── 任一环节失败返回阶段3修正 ────────┘
```

**阶段 1 — Init（项目初始化）**
触发：新 MCU 任务启动（全新项目/旧项目修改/旧项目移植）或 `ff init` 命令。

多路探测自动识别 board：
1. **USB 端口扫描**（MVP）：pyserial 枚举 COM/LPT，读取 USB VID/PID，查表匹配已知 board 指纹
2. **workspace 文档分析**（P2 增强）：扫描工作空间下已有 board.json / 项目文件 / README
3. **原理图分析**（P2 增强）：解析 KiCad `.kicad_sch` / 网表（§2.7 原理图 ingestion）
4. **用户文本分析**：LLM 从用户输入的自然语言中提取板级信息

多路融合 → board 确定 → 加载 board.json + vendor 引用 + knowledge 索引 + Skill 路由 → 按需加载资源。
穷尽方法无法判断 → 主动询问用户 board 信息。

**阶段 2 — Plan（项目规划）**
输入：用户功能需求 + Init 阶段确定的 board 信息。
产出：`<workspace>/.firmforge/plan.md`（人类可读规划文件）。

PlanGenerator 调用 Plan 相关资源（knowledge + constraints + features），生成规划草案：
- 功能分解（功能点清单）
- 模块划分 + 接口定义
- 模块依赖图
- 测试策略
- 调度模式建议（批处理 / 模块级流水线，见 §2.9.2）

用户审查 `plan.md`：
- 确认 → 锁定 plan，进入阶段 3
- 提出修改意见 → AI 按 feedback 重生成 plan.md → 迭代直至确认

**阶段 3 — Code（模块编码 + 微流水线）**
依据锁定的 plan.md，分步骤、分模块编码实现。

**每完成一个功能代码模块，立即开展该模块的微流水线**：
1. 代码审查（review Skill）：Lint、函数原型审计、参数溯源、safety_check、constraints 守卫
2. 代码编译（BuildProvider）：捕获编译器反馈信息
3. 代码下载（FlashProvider）：捕获下载反馈信息
4. 代码测试（TestProvider + test Skill）：模块级测试用例、串口调试、HIL
5. 代码验证（verify Skill）：自动化综合评估 + 人工确认

任一环节失败 → 返回修正该模块代码 → 再次循环 → 直至该模块全链路通过。

> **批处理模式**（简单项目，见 §2.9.2）：跳过模块级微流水线，所有代码生成完毕后直接进入阶段 4 整体编译。

**阶段 4 — Build（项目编译）**
所有模块代码完成后，调用编译器编译全部代码，捕获分析编译信息。
失败 → 返回阶段 3 修正编码（按编译错误→模块映射定位）。

**阶段 5 — Flash（项目下载）**
阶段 4 成功后，下载项目代码到硬件，捕获下载反馈信息。
失败 → 返回阶段 3 修正编码。

**阶段 6 — Test（项目测试）**
阶段 5 成功后，开展完整项目测试：
- 项目级测试用例
- 串口调试信息
- HIL 技术
失败 → 返回阶段 3 修正编码。

**阶段 7 — Verify（项目验证）**
自动化综合评估验证 + 人工验收确认：
- 自动化评估：编译成功率 / 测试通过率 / 覆盖率 / 静态分析评分
- 人工确认：最终产品行为是否满足原始需求
- 验收报告：LLM 生成摘要 + 关键证据（编译日志/测试日志/串口回放）

#### 2.9.2 调度模式自动选择

ToolOrchestrator 根据 plan.md 的**功能点数量**自动选择调度模式：

| 功能点数量 | 调度模式 | 说明 |
|-----------|---------|------|
| ≤ 2 | **批处理模式** | 全自动闭环优先：所有代码生成完毕 → 整体编译 → 整体烧录 → 整体测试。效率高，适合 blink/serial_echo 类单外设任务。 |
| > 2 | **模块级流水线模式** | 强制走模块级微流水线：每个模块写完立即 review→compile→flash→test→verify。错误定位精确到模块，稳步验收产物。 |

> **硬件可达性前置**：模块级流水线模式要求硬件全程在线。`ff init` 检测到硬件不在线时，强制降级为批处理模式（仅生成+编译，不烧录不测试），并提示用户连接硬件后再执行 `ff run`。

> **用户覆盖**：`ff config --mode batch|module-level|auto`（默认 auto）。

#### 2.9.3 .plan 文件交互协议

```
<workspace>/.firmforge/plan.md
```

结构（Markdown + YAML frontmatter）：
```yaml
---
plan_id: <uuid>
board: arduino_mega
intent: "串口回显大写 + LED 心跳"
mode: module-level          # auto | batch | module-level
feature_points: 3           # 功能点数量
status: draft               # draft | reviewed | locked
created_at: <ISO8601>
---

## 功能分解
1. UART 初始化（9600 8N1）
2. 回显处理（大写转换）
3. LED 心跳（1Hz）

## 模块划分
| 模块 | 文件 | 依赖 | 测试策略 |
|------|------|------|---------|
| uart_init | apps/echo/uart_init.c | 无 | 串口回读启动消息 |
| echo_loop | apps/echo/echo_loop.c | uart_init | 发送"hello"→回读"HELLO" |
| heartbeat | apps/echo/heartbeat.c | 无 | LED 视觉确认 |

## 模块依赖图
uart_init ← echo_loop
heartbeat (独立)

## 测试策略
模块级：每模块独立测试用例
项目级：集成后串口回放完整会话

## 调度建议
功能点 = 3 > 2 → 模块级流水线模式
```

交互流程：
1. PlanGenerator 生成 `plan.md`（status: draft）
2. CLI 输出摘要 + 提示用户审查
3. 用户编辑 `plan.md` 或命令行反馈
4. PlanGenerator 按 feedback 重生成（status: draft）
5. 用户确认 → status: locked → 进入阶段 3
6. 阶段 3-7 执行中如发现 plan 需调整，用户可解锁（status: draft）重新迭代

#### 2.9.4 与状态机（§2.5）的映射

7-Stage Pipeline 的错误恢复由 §2.5 状态机承接，映射关系：

| Pipeline 阶段 | 状态机状态 | 失败动作 |
|--------------|-----------|---------|
| 3.Code - 编译 | COMPILE_FIX_LOOP | parse→fix→rebuild（≤3 轮）→失败沉淀经验账本 |
| 3.Code - 下载 | FLASH_RETRY | 重试（≤2 次）→失败转人工 |
| 3.Code - 测试 | TEST_DIAGNOSE | 诊断+修正→失败转人工 |
| 4.Build | COMPILE_FIX_LOOP | 同上，错误范围按编译日志→模块映射 |
| 5.Flash | FLASH_RETRY | 同上 |
| 6.Test | TEST_DIAGNOSE | 项目级测试诊断 |
| 连续失败 | GIVE_UP | 报告+沉淀经验账本 |

> **错误传播范围**：由"编译错误信息 + 模块依赖图（plan.md 生成）"共同决定。单模块错误只改该模块；若错误涉及接口（依赖图节点），触发依赖模块回归测试。

---

### 2.10 LLM 代码生成分层混合路线（v2.4 新增）

为化解"约束生成"与"自由生成"的技术路线分歧，经业界对标（Copilot/Cursor/Embedder）与学术研究（SemGuard/SCodeGen/ICSME'25）论证，确立**分层混合路线**。详细论证见 `docs/技术路线分析-LLM代码生成约束策略.md`。

#### 2.10.1 三层架构

```
┌─────────────────────────────────────────────────┐
│ Layer 1: 规则约束（soft constraint）             │
│ - paradigm 范式驱动代码风格（arduino/register/hal）│
│ - 安全规则（ISR 禁阻塞等）                        │
│ - 知识库 API/寄存器参考作为"推荐"注入 prompt       │
│ → LLM 自由生成，但知道应该用什么风格              │
├─────────────────────────────────────────────────┤
│ Layer 2: 引用验证（hard gate）                    │
│ - Citation Gate: 寄存器/位域必须可解析            │
│ - 不可解析 → 阻断编译                             │
│ → 拦截幻觉寄存器（v2.3 引用门禁的核心价值）        │
├─────────────────────────────────────────────────┤
│ Layer 3: 行为验证（empirical）                    │
│ - 编译验证（语法）                                │
│ - HIL 串口验证（行为）                            │
│ - Confidence 评分（置信度，<58% 转人工）           │
│ - COMPILE_FIX_LOOP（自动修复）                    │
│ → 拦截语法错误和部分行为错误                      │
└─────────────────────────────────────────────────┘
```

#### 2.10.2 核心决策：知识库角色变更

| 原设计（v2.3） | v2.4 变更 | 理由 |
|--------------|----------|------|
| 知识库 = 允许列表（LLM 只能使用已索引的 API） | 知识库 = **验证基准**（LLM 自由生成，闸门把关） | 知识库不完整时不阻塞；多 MCU 扩展成本低 |
| "只使用原厂库函数编程" | "自由生成 + Citation Gate 验证" | 安全闸门已验证能拦截幻觉；LLM 创造力不被限制 |
| CodeGenerator prompt 不区分风格 | board.json `paradigm` 驱动 | Arduino 板→Arduino API，裸 MCU→寄存器 |

#### 2.10.3 对标业界

| 维度 | 通用工具（Copilot/Cursor） | 嵌入式标杆（Embedder） | FirmForge（v2.4） |
|------|--------------------------|----------------------|-------------------|
| 生成策略 | 自由生成 + Linter/编译兜底 | 约束生成 + 硬件验证 | 规则约束 + 引用验证 + 编译/HIL 验证 |
| 知识库角色 | 增强上下文（retrieval-augmented） | 硬约束（datasheet 引用必须存在） | 验证基准（软增强 + 硬验证） |
| 知识库不完整时 | 不受影响 | 阻塞（无法生成） | 降级为编译兜底 |

#### 2.10.4 未来演进

`paradigm_locked: true`（安全关键场景）可启用"约束生成"模式——此时知识库必须完整，生成阶段即排除未索引的 API。非安全关键场景保持自由生成。

### 2.11 Layer 1 编程范式推断引擎（v2.4 新增）

在 Init 阶段（7-Stage Pipeline §1），根据板子身份、MCU 系列、用户意图、工具链可用性，自动推断最适合的编程范式，注入 CodeGenerator prompt。详细规范见 `docs/Layer1-范式选择规则规范.md`。

#### 2.11.1 范式定义

| paradigm | 典型 API | 适用场景 |
|----------|---------|---------|
| `arduino` | `pinMode` / `digitalWrite` / `Serial.begin` / `delay` | Arduino 板，教学/原型/快速开发 |
| `hal` | `HAL_GPIO_WritePin` / `HAL_UART_Transmit` | STM32 产品级开发，CubeMX 生态 |
| `ll` | `LL_GPIO_SetOutputPin` / `LL_USART_TransmitData8` | STM32 实时/电机控制/关键路径 |
| `register` | `DDRB` / `PORTB` / `GPIOA->BSRR` | AVR 裸片，极致优化，学习底层 |
| `esp_idf` | `gpio_set_level` / `uart_write_bytes` | ESP32 生产级，WiFi/BT/FreeRTOS |

#### 2.11.2 决策引擎——四级优先级

```
board.json 显式指定 (paradigm字段) → 用户意图关键词匹配 → 板子身份+工具链 → MCU 系列默认
```

**决策规则摘要**：

| 板子身份 | MCU | 用户意图关键词 | 工具链 | → paradigm |
|---------|-----|--------------|--------|-----------|
| Arduino 板 | AVR | — | Arduino Core 可用 | `arduino` |
| Arduino 板 | AVR | "寄存器/底层/裸机" | — | `register` |
| 裸 MCU | AVR | — | 无 Arduino Core | `register` |
| — | STM32 | "生产/CubeMX" | HAL 可用 | `hal` |
| — | STM32 | "实时/电机" | LL 可用 | `ll` |
| — | STM32 | "学习寄存器" | — | `register` |
| ESP32 | ESP32 | "WiFi/FreeRTOS" | ESP-IDF 可用 | `esp_idf` |
| ESP32 | ESP32 | "Arduino/原型" | Arduino Core 可用 | `arduino` |
| 任何 | 任何 | 显式指定 `paradigm` + `paradigm_locked: true` | — | 用户指定值（锁定，不可覆盖） |

#### 2.11.3 board.json 扩展

```json
{
  "board_type": "arduino_board",    // arduino_board | bare_mcu | dev_board
  "paradigm": "arduino",             // 显式指定（留空由引擎推断）
  "paradigm_locked": false,          // true=安全关键场景锁定
  "mcu": { "family": "avr" }        // MCU 家族（推断关键因子）
}
```

#### 2.11.4 范式驱动的代码生成

CodeGenerator 根据推断的 paradigm 注入对应的 prompt 规则：

- `arduino`: "使用 pinMode/digitalWrite/Serial，禁止直接操作 DDRB/PORTB"
- `register`: "使用 DDRB/PORTB/UCSR0B 直接寄存器操作，禁止 pinMode"
- `hal`: "使用 HAL_GPIO_WritePin/HAL_UART_Transmit，禁止直接寄存器"

Citation Gate 行为也根据 paradigm 调整：
- `arduino`: 校验 API 函数名在 api.json 中存在；寄存器引用仅 warning
- `register`: 强制校验每个寄存器名在 reference 库中存在；未索引 → error 阻断

---

## 三、四大重点建设

### 3.1 板级支持（BSP + board.json）

#### 3.1.1 board 顶层组织

以电路板为代码组织顶层单位。每块板一个目录，含板级知识 + 引脚配置 + 应用代码。芯片系列库在 vendor 层被引用复用，不复制。

```
boards/
├── arduino_mega/                    # Arduino Mega 2560
│   ├── board.json                   # 板级知识 + vendor 引用索引
│   └── apps/<task>/                 # 应用代码（.ino/.cpp）
│   # 无独立 bsp 代码——复用 Arduino variant（原厂已提供板级支持）
│
└── stm32f103vet6_minisys/           # STM32F103VET6 最小系统板
    ├── board.json                   # 板级知识 + vendor 引用索引
    ├── bsp_config.h                 # 板级引脚配置（LED=PE5 等）
    ├── LinkerScript.ld              # 链接脚本（按芯片型号 Flash/RAM）
    └── apps/<task>/                 # 应用代码
```

#### 3.1.2 BSP 分治（按原厂提供度）

| | Arduino | STM32 |
|---|---------|-------|
| 原厂提供板级支持 | ✅ variant 完整 | ❌ HAL 不管板子 |
| BSP 代码厚度 | 极薄（复用 variant） | 实打实（引脚+复用+RCC 前置） |
| board 目录内容 | board.json + apps | board.json + bsp_config + LinkerScript + apps |
| vendor 层 | Arduino core + variants（arduino-cli/PlatformIO 管理） | HAL + CMSIS + BSP 基类 |

#### 3.1.3 board.json schema

```json
{
  "board_name": "Arduino Mega 2560",
  "platform": "arduino",
  "mcu": { "series": "avr", "chip": "ATmega2560" },
  "fqbn": "arduino:avr:mega",
  "vendor_ref": {
    "core": "arduino-cli-managed",
    "note": "Arduino core + variant 由 arduino-cli 自带管理"
  },
  "pins": { "led_builtin": 13, "i2c": "SDA=20,SCL=21" },
  "specs": { "flash": "256KB", "ram": "8KB", "clock": "16MHz" },
  "constraints": {
    "isr_forbidden": ["blocking_calls", "malloc"],
    "pin_avoid": [],
    "peripheral_rules": { "i2c": "must_open_drain" }
  },
  "features": {
    "gpio": true,
    "uart": true,
    "spi": false,
    "i2c": false,
    "pwm": false
  },
  "schematic_source": "manual_entry"
}
```

> `constraints`（§2.8.2 硬件宪法约束注入）：MCU 物理约束声明，Codegen Skill 生成代码前作为系统提示注入。对齐 BSP 设计准则第 2 条"AI 难以犯错"。
> `features`（§2.8.2 Kconfig 功能裁剪）：声明式功能级开关，板级预设可覆盖，控制外设/协议/特性的编译开关。对齐 BSP 设计准则第 7 条"封装最小化"——不用的特性不生成相关代码。
> `schematic_source` 取值：`manual_entry`（MVP 默认，人工录入）/ `kicad_netlist`（§2.7 原理图 ingestion 自动化解析，增量能力）。远期可扩展 PDF/图片识别。

### 3.2 芯片 RAG 知识库

#### 3.2.1 知识库协议改进（应用 P0/P1）

| 改进项 | 内容 |
|-------|------|
| P0-1 SVD 映射 | STM32 直接导入官方 SVD；Arduino 无 SVD，自研 AVR Profile |
| P0-2 RRF 融合 | hybrid_search 改为 list[ScoredHit]，实现 RRF(k=60) 统一排序 |
| P1-1 声明式生成 | api.json 从头文件 Doxygen + clang AST 自动提取 |
| P1-2 标准 schema | $schema 改用 JSON Schema 2020-12 draft |
| P1-3 错误模型 | errors 改为 {code, severity, behavior, ai_hint} |
| P1-4 强类型引用 | register_config 改为 {register, field, value} + $ref |

#### 3.2.2 三库分层

- **文档/寄存器参考库（reference）**：JSON Schema 严格定义，精确查表（寄存器、引脚、时钟）
- **API 契约库（api）**：JSON + Code，向量检索为主（原厂 API 契约 + 用例）
- **社区资源库（community）**：JSONL + Markdown，向量检索为主

#### 3.2.3 双存储分层

精确查表（JSON）+ 语义检索（ChromaDB）分离，对症嵌入式"寄存器表 + 手册叙述"的混合知识形态。

### 3.3 社区技术资料知识库

按板子/平台分库采集：
- Arduino：forum.arduino.cc + Project Hub + GitHub 示例
- STM32：ST 社区 + CubeMX 示例 + GitHub 项目
- 质量门禁：`forum_qa.verified` 结构化（status/method/evidence_url）

### 3.4 Skill 体系

四类 Skill 覆盖 AI 编程全生命周期，每种 Skill 内部按子类型路由分发（§2.8.1 路由型 Skill）：

```
skills/
├── codegen/
│   ├── _router.md          # 路由：按外设类型分发
│   ├── gpio_driver/
│   ├── uart_driver/
│   ├── spi_driver/
│   └── ...
├── review/
│   ├── _router.md          # 路由：按审查类型分发
│   ├── precondition_check/
│   ├── safety_check/
│   ├── side_effect_check/
│   └── ...
├── test/
│   ├── _router.md          # 路由：按测试模式分发
│   ├── hil_assert_gen/
│   ├── test_case_gen/
│   └── ...
└── verify/
    ├── _router.md          # 路由：按验证阶段分发
    ├── compile/
    ├── flash/
    ├── hil_run/
    └── verdict/
```

> **路由机制**：`_router.md` 根据请求特征（外设类型/审查类型/测试模式）分发到对应子技能，避免全量 Skill 加载到上下文浪费 Token。与三层 Token 优化（§2.8.2）的按需加载策略联动。
> **CI 质量保证**（§2.8.2 Skill CI 验证）：`validate_skills.py` 校验 SKILL.md frontmatter 格式 + 触发条件完整性 + 示例可执行性；CI 流水线每次提交自动运行校验。Skill 写错会导致 AI 生成错误代码——编译期否决。
> **与 7-Stage Pipeline 的关系**（§2.9）：四类 Skill 覆盖阶段 3-7（Code/Build/Flash/Test/Verify）。阶段 1（Init）由 `BoardDetector` 承接，阶段 2（Plan）由 `PlanGenerator` 承接——这两个阶段不是 Skill，而是 Agent Core 组件，因为它们涉及用户交互和状态管理，不适合无状态的 Skill 模式。

---

## 四、技术选型

### 4.1 裸工具链（免费 + CLI + 无商业授权）

| 工具 | 用途 | 系列 | 许可证 |
|------|------|------|--------|
| avr-gcc | 编译 | Arduino | GPL + linking exception |
| avrdude | 烧录 | Arduino | GPL |
| arm-none-eabi-gcc | 编译 | STM32 | GPL + linking exception |
| openocd | 烧录/调试 | STM32 | GPL |
| make | 构建 | 通用 | GPL |

> **不用 PlatformIO 平台**。Provider 直接调用裸工具 CLI。PlatformIO 仅作为工具链获取渠道（可选），不作为运行时依赖。

### 4.2 工具链分发机制（三段式 + 版本追踪）

1. **Agent 安装包带 bootstrap**（~50MB，不含工具链本体）
2. **首次指定板子时，板级感知按需安装**：从国内镜像下载预打包 bundle（arduino_bundle.zip / stm32_bundle.zip），解压到 `~/.firmforge/toolchains/`（遵循业界惯例：产品名作点号前缀，类比 ~/.platformio/ ~/.rustup/），不污染系统 PATH
3. **LLM 运行时兜底**：执行时检测缺工具，触发自动安装

> 初期用 winget + bootstrap 脚本（零维护）；用户量上来后上 OSS 镜像 + 预打包 bundle。

**多平台版本追踪**（§2.8.2，借鉴 TuyaOpen `platform_config.yaml`）：`infrastructure/platform_config.yaml` 追踪各 vendor SDK + 工具链的 commit/版本号，确保平台层版本一致性。与 v2.1 版本锚定机制（编译期 `_Static_assert` 校验运行时版本）互补——此处管分发版本一致性，彼处管运行时版本校验。

**双层的 `.firmforge` 目录约定**：

| 层级 | 路径 | 存放内容 | 类比 |
|------|------|---------|------|
| **系统级**（跨项目共享） | `~/.firmforge/toolchains/` | avr-gcc / avrdude / arm-gcc / openocd / Arduino core | `~/.platformio/tools/` `~/.rustup/toolchains/` |
| **项目级**（每个 workspace 一份） | `<workspace>/.firmforge/` | plan.md / ledger.jsonl / trace_*.jsonl | `<repo>/.git/config` `.vscode/` |

> 原则：工具链是系统资源——多项目共用不重复安装，放 `~/.firmforge/`。项目特定产物（规划、经验、执行轨迹）放 `<workspace>/.firmforge/`。两层互不污染。业界参照：PlatformIO `~/.platformio/` vs `<project>/platformio.ini`；Rust `~/.rustup/` vs `<project>/target/`。

### 4.3 其他选型

| 维度 | 选型 | 理由 |
|------|------|------|
| 核心语言 | Python 3.10+ | pyserial/pyocd 生态，MCP 协议原生 |
| RAG 引擎 | ChromaDB + Embedding | 本地离线 |
| MCP 协议 | stdio(本地) + SSE(远程) | Codebuddy 标准 |
| Tracing | JSONL 本地文件 | 轻量 |
| 寄存器描述 | CMSIS-SVD | STM32 官方；Arduino 自研 AVR Profile |

### 4.4 CH340 USB 串口驱动兼容策略（2026-07-18 铁证定案）

> **根因**：CH340 驱动 3.5 正常；3.9.2024.9 / 4.0 有 bug——`SetCommState` 目标==残留波特率时返回 `ERROR_GEN_FAILURE(31)`。不是 pyserial / FirmForge 代码缺陷，是驱动版本问题。Win11 默认推送 4.0。外部串口工具（非 STC-ISP）在 3.9/4.0 下也会打不开——STC 不受影响因其做了波特率过渡。

> **策略**：pyserial 优先（正常驱动 fast path），Win32Serial toggle fallback（buggy 驱动自动接管）。不检测驱动版本，自适应——和 STC-ISP 一样"下载即用，不挑驱动"。

**三层兼容保障**：

| 阶段 | 步骤 | 机制 |
|---|---|---|
| S1 Init | `detect_port` | pyserial `list_ports` 枚举（只读，无同值问题） |
| S1 Init | serial sig 读取 | `ComPort`（已有 fallback） |
| S5 Flash 前 | `_bootloader_reset` 1200 DTR | 双用途：残留→1200 + 触发 bootloader → avrdude open(115200) 异值 |
| S5 Flash 后 | `com_port_clean_close` | pyserial 先试 → 失败 Win32Serial toggle fallback |
| S6 Test | `ComPort.__enter__` | pyserial `Serial.open` → 失败 `Win32Serial.open`（toggle 自愈） |

**代码模块**：

| 模块 | 角色 |
|---|---|
| `flash.py` → `ComPort` | 自适应上下文管理器 |
| `flash.py` → `com_port_clean_close` | S5 后端口清理 |
| `flash.py` → `_bootloader_reset` | 1200 DTR 复位（双用途） |
| `win32serial.py` | Fallback 模块 —— open 时 toggle 自愈，仅 pyserial 失败时调用 |
| pyserial | Fast path + 端口枚举 |

**驱动兼容矩阵（已验证）**：

| 驱动版本 | pyserial 同值 | FirmForge 管道 | 外部工具 |
|---|---|---|---|
| 3.5 | ✅ OK | pyserial fast path ✅ | 正常 ✅ |
| 3.9.2024.9 | ❌ GEN_FAILURE | Win32Serial fallback ✅ | 失败 ❌ |
| 4.0 | ❌ GEN_FAILURE | Win32Serial fallback ✅ | 失败 ❌ |

**禁止项**：close 时主动改残留（过度设计）；`SetCommBreak`（崩 CH340 设备需重插）；检测驱动版本号（维护成本高）。

> 详细信息见项目长期记忆 `MEMORY.md` 第十节。实现见 `firmforge/providers/arduino/flash.py`（ComPort/com_port_clean_close）和 `firmforge/providers/arduino/win32serial.py`（Win32Serial fallback）。

---


```
MCU/
├── docs/                           # 设计文档
├── boards/                         # ← 顶层：按电路板组织
│   ├── arduino_mega/
│   │   ├── board.json
│   │   └── apps/<task>/
│   └── stm32f103vet6_minisys/
│       ├── board.json
│       ├── bsp_config.h
│       ├── LinkerScript.ld
│       ├── Makefile
│       └── apps/<task>/
├── vendor/                         # ← 复用层：芯片系列库，被引用不复制
│   ├── arduino/                    # Arduino core + variants（或由 arduino-cli 管理）
│   └── stm32/
│       ├── hal/stm32f1xx/          # ST 官方 HAL（git submodule）
│       ├── cmsis/stm32f1xx/        # CMSIS + startup
│       └── bsp/stm32f1xx/          # BSP 基类（RCC/复用/模板，自研）
├── firmforge/                      # FirmForge 核心 Python 包（内部名 firmforge）
│   ├── core/                       # 型号无关核心
│   │   ├── board_detector.py       # 7-Stage §1：USB 扫描 + VID/PID 匹配 board
│   │   ├── plan_generator.py       # 7-Stage §2：.plan 文件生成 + 用户迭代
│   │   ├── code_generator.py       # 7-Stage §3：分模块代码生成
│   │   ├── tool_orchestrator.py    # 7-Stage §3-7：调度模式选择 + 流水线编排
│   │   ├── agent_state_machine.py  # 错误恢复状态机（模块级/项目级双作用域）
│   │   ├── experience_ledger.py    # 经验账本（跨会话）
│   │   ├── context_manager.py      # 三层 Token 优化加载
│   │   └── skill_engine.py         # Skill 加载/路由分发
│   ├── providers/                  # MCU 适配器（base.py 是分治边界）
│   ├── infrastructure/             # 基础设施：RAG/HIL/Skills Repo/Tracing/platform_config.yaml
│   └── adapters/                   # CLI(ff init/gen/run) /MCP
├── skills/                         # Skill 仓库
├── knowledge/                      # 知识层：RAG 知识库（reference/api/community/vectors）
├── tests/
└── <workspace>/.firmforge/         # 7-Stage Pipeline 运行时产物（每项目）
    └── plan.md                     # §2.9.3 规划文件（draft→reviewed→locked）
```

---

## 六、开发阶段计划（Arduino 优先单线）

### 阶段 0：Arduino 环境与链路验证（1-2 周）
- 安装 avr-gcc + avrdude（裸工具链）
- 编译 blink + 烧录 Mega2560 + LED 闪烁
- **验证点**：完整闭环跑通 ✅（已于 2026-07-08 验证通过）

### 阶段 1：Arduino BSP + 核心框架（4 周）
- board.json schema 定型（含 `constraints` + `features` 新增字段）
- `providers/base.py` 接口协议（分治边界，必须守住）
- `agent_state_machine.py` 错误恢复状态机（含 COMPILE_FIX_LOOP 实现范式 + 模块级/项目级双作用域）
- `experience_ledger.py` 经验账本（与 Agent Trace 并列）
- Skill 引擎骨架（含 `_router.md` 路由层）
- 三层 Token 优化加载策略（常驻/会话/按需三层）
- **7-Stage Pipeline 阶段 1-2 模块**（§2.9）：`board_detector.py`（USB 扫描 + VID/PID 匹配，MVP 范围）、`plan_generator.py` + `.plan` 文件协议（`<workspace>/.firmforge/plan.md`）、`ff init` 命令骨架

### 阶段 2：Arduino RAG 知识库 + 公共设施（4 周）
- 自研 AVR SVD Profile
- Arduino API 契约知识库
- HIL 框架（assert + 串口收集；§2.7 硬件信号回灌闭环作为后期硬验证扩展）
- `infrastructure/platform_config.yaml` 多平台版本追踪
- Skill CI 验证流水线（`validate_skills.py` + CI）

### 阶段 3：Arduino Provider + Skill + CLI 闭环（4 周）
- Arduino BuildProvider（avr-gcc 封装）
- Arduino FlashProvider（avrdude 封装）
- 四类 Skill 实现
- **7-Stage Pipeline 阶段 3-7 模块**（§2.9）：ToolOrchestrator 调度模式自动选择（功能点阈值 ≤2 批处理 / >2 模块级流水线）、模块依赖图执行引擎、`ff run` 命令串联 7 阶段全流程、硬件可达性检测降级逻辑
- **验证点（关键里程碑）**：自然语言 → Arduino 硬件全自动跑通（批处理模式）；多模块任务走模块级流水线闭环
> 通过后启动 STM32 线（阶段 5），复用核心框架。

### 阶段 4：Arduino MCP 适配器 + 社区知识库 + Benchmark（4 周）

### 阶段 5：STM32 线启动（按板子，复用核心框架）
- STM32F103VET6 BSP（bsp_config + BSP 基类 + HAL 引用）
- BSP 基类内部分层参考 TuyaOpen TKL/TAL/TDL/TDD 范式（§2.8.3 设计预留）：内核抽象（RCC/中断）→ 功能抽象（外设封装模板）→ 设备类（具体驱动）分层
- STM32 Provider（arm-none-eabi-gcc + openocd）
- STM32 知识库（官方 SVD 导入）

### 阶段 6+：扩展其余板子/MCU
- STM32F4 / STM32H7 / ESP32 / GD32 / STC8H

---

## 七、风险矩阵

| 风险 | 等级 | 应对 |
|------|------|------|
| Arduino API 覆盖度 | 中 | 阶段 0 验证 I2C/SPI 覆盖 |
| AVR SVD 自研工作量 | 中 | 参考 Microchip ATDF，复用 CMSIS-SVD XML |
| 型号级分治边界失守 | 🟠 中 | 守住 `providers/base.py`，STM32 线只填适配层 |
| 工具链下载体验差 | 中 | 预打包 bundle + 国内镜像（中期） |
| GitHub 不可达 | 中 | 工具链从 winget/国内镜像获取，不依赖 GitHub |
| STM32 线启动时机 | 🟡 低 | 阶段 3 验证点通过即启，可与阶段 4 并行 |
| USB VID/PID 覆盖不全（7-Stage §1） | 中 | MVP 先覆盖已知 Arduino/ST-Link，未匹配时询问用户；逐步扩充指纹库 |
| 模块级流水线烧录次数多（7-Stage §3） | 中 | 硬件不在线自动降级批处理；功能点阈值可调 |
| .plan 用户迭代体验（7-Stage §2） | 低 | Markdown 可读性好，CLI 辅助提示审查要点 |

---

## 八、关键决策（v2.3）

1. **AHL 退役**（v2.3）：AHL 作为代码层名字完全下线。设计原则转为"BSP 设计准则"。
2. **board 顶层架构**（v2.3）：以电路板为代码组织顶层单位，vendor 芯片库引用复用。
3. **Arduino 不做封装层**（v2.3）：原厂 API 已 AI 友好，直接用 + variant，封装破坏 RAG 语料。
4. **STM32 用 BSP + 模板替代独立 AHL**（v2.3）：板级引脚配置 + 程序化强制初始化模板 + 自检，防静默失败。
5. **裸工具链**（v2.3）：avr-gcc+avrdude / arm-none-eabi-gcc+openocd，不用 PlatformIO 平台。
6. **首发 Arduino 单线**（v2.2）：STM32 推后至阶段 3 验证点通过后启动。
7. **框架复用边界**（v2.2）：Agent 核心型号无关，`providers/base.py` 是必须守住的边界。
8. **AI 成功率优先于统一**（v2.2）：跨 MCU 统一与 AI 成功率冲突时，让位于后者。
9. **SVD 优先**：STM32 官方 SVD，Arduino 自研 AVR Profile。
10. **API 契约自动生成**：头文件 Doxygen + clang AST 提取。
11. **四类 Skill 体系**：codegen/review/test/verify。
12. **错误恢复状态机**：编译 3 轮 / 烧录 2 次 / 超时放弃。
13. **STC8H 推迟到阶段 6+**。
14. **安全加固 Skill**（v2.1）：`review/safety_check` 烧录前强制门禁。
15. **版本锚定**（v2.1）：`_Static_assert` 编译期校验。
16. **增量代码生成**（v2.1）：`merge_to_existing` AST 合并。
17. **知识保鲜**（v2.1）：`freshness_check` CI。
18. **可移植性评估**（v2.1）：`portability_check` 迁移成本评估。
19. **FirmForge 7-Stage Pipeline**（2026-07-11）：端到端工作流分 7 阶段（Init→Plan→Code→Build→Flash→Test→Verify）。调度模式按功能点数量自动选择（≤2 批处理 / >2 模块级流水线）。`.plan` 文件作为用户审查载体。USB 扫描+VID/PID 匹配进 MVP，原理图扫描归 P2（§2.9）。

---

## 九、补充设计（v2.1 五项，保留）

### 9.1 安全加固 Skill（P0，阶段 3）
`review/safety_check`：看门狗/HardFault/栈溢出烧录前强制校验；并承载 §2.7 置信度评分闸门——生成的关键配置值置信度低于阈值时升级为人工复核。

### 9.2 版本锚定头文件（P0，阶段 1）
`_Static_assert` 编译期校验 BSP/库版本。

### 9.3 增量代码生成（P1，阶段 3）
`operation_mode: merge_to_existing`，AST 分析按需合并。

### 9.4 知识保鲜机制（P1，阶段 2）
`freshness_check` CI 检测知识库过期与不一致。

### 9.5 跨 MCU 可移植性评估（P2，阶段 4+）
`portability_check` Skill，迁移成本评估报告。

---

## 十、验证记录

### 10.1 Arduino Mega2560 完整闭环（2026-07-08 验证通过 ✅）

| 环节 | 工具 | 结果 |
|------|------|------|
| 代码 | `boards/arduino_mega/apps/blink/blink.ino` | pinMode/digitalWrite LED_BUILTIN |
| 编译 | avr-gcc 7.3.0 | ✅ firmware.hex，Flash 0.6%（1536B） |
| 烧录 | avrdude 8.1 `-c wiring -P COM5 -b 115200` | ✅ 1536B 写入 + verify 通过 |
| 运行 | Arduino Mega2560 硬件 | ✅ LED 闪烁 |

### 10.2 Arduino API 心跳 E2E（2026-07-12 验证通过 ✅）

| 环节 | 工具 | 结果 |
|------|------|------|
| 范式推断 | ParadigmResolver | ✅ paradigm=arduino（board.json 显式） |
| Plan 生成 | PlanGenerator | ✅ 3 features, auto mode |
| 代码生成 | CodeGenerator + LLM | ✅ Arduino API 风格（pinMode/digitalWrite/Serial.print/delay） |
| Citation Gate | CitationValidator | ✅ PASS（0 errors） |
| 置信度 | ConfidenceScorer | ✅ 100%（0 review items） |
| 编译 | avr-g++ + Arduino Core（24 源文件） | ✅ firmware.hex，15,252B（5.9%） |
| 烧录 | avrdude 8.1 wiring COM7 115200 | ✅ |
| 串口验证 | HIL Framework | ✅ "FirmForge heartbeat: N" 输出确认 |
| 全链路 | 7-Stage Pipeline | ✅ ALL 7 STAGES PASSED（17.9s） |

### 10.3 STM32F103VET6（待验证）
工程文件已就绪（startup_stm32f103xe.s + LinkerScript.ld + main.c + Makefile），待 ARM GCC 安装后编译验证。

---

> v2.3 变更登记：AHL 退役为 BSP 设计准则；board 顶层 + vendor 复用架构定型；裸工具链选型；吸收知识库协议 P0/P1 与 AHL 设计原则 5 补丁；Arduino 优先单线；工具链分发机制三段式；吸收竞品 Embedder 四项机制（引用门禁→validator / 置信度评分→safety / 硬件信号回灌→HIL / 原理图 ingestion→board.json，见 §2.7）。Arduino Mega2560 完整闭环验证通过。**本规划文档为项目唯一最高纲领性文件；原知识库协议等文档已移入 `docs/历史/`，仅作历史参考，不再作为开发准则。**
>
> **2026-07-11 竞品借鉴融合更新**（§2.8 新增 + 各节联动）：吸收 6 仓库横向对比的 P0/P1 借鉴项：经验账本→Agent Core / 路由型 Skill→Skill Engine / AI 编译修复闭环→状态机 / 硬件宪法约束→board.json constraints / 三层 Token 优化→上下文管理 / Skill CI 验证→Skills Repo / Kconfig 功能裁剪→board.json features / 多平台版本追踪→工具链分发。竞品分析报告归档至 `docs/历史/`。
>
> **2026-07-11 7-Stage Pipeline 新增**（§2.9 + §2.2/§2.5/§5/§6/§七/§八 联动）：确立用户视角端到端工作流 7 阶段（Init→Plan→Code→Build→Flash→Test→Verify）。调度模式按功能点数量自动选择（≤2 批处理 / >2 模块级流水线）。`.plan` 文件作为用户审查载体。USB 扫描+VID/PID 匹配进 MVP，原理图扫描归 P2。新增模块：BoardDetector / PlanGenerator / ToolOrchestrator 调度模式选择。
>
> **2026-07-11 文件格式约定**（§2.6.4 新增）：四类格式映射——A 类人类编辑优先（MD+YAML frontmatter: plan.md/SKILL.md/_router.md），B 类机器读写优先（JSON+Schema: board.json/api.json/reference），C 类流式追加（JSONL: ledger/trace/sm_trace），D 类仅扁平单层时 YAML（platform_config.yaml）。核心原则：可编辑性>可读性>可解析性>可流式写入。
>
> **2026-07-12 v2.4 升级：LLM 代码生成分层混合路线 + Layer 1 范式推断引擎**
> - **新增 §2.10**：LLM 代码生成分层混合路线——确立三层架构（Layer 1 规则约束 → Layer 2 引用验证 → Layer 3 行为验证），替代"只使用原厂库函数"的硬约束思路。知识库角色从"允许列表"变为"验证基准"。对标 Copilot/Cursor/Embedder 业界最佳实践。
> - **新增 §2.11**：Layer 1 编程范式推断引擎——五种范式（arduino/hal/ll/register/esp_idf），board.json `paradigm` 字段 + Init 阶段四级决策自动推断。范式驱动 CodeGenerator prompt 规则和 Citation Gate 校验策略。
> - **更新 §2.2 架构**：Agent Core 加入 ParadigmResolver 模块。
> - **更新 §2.3 调用链**：体现范式驱动的代码风格选择（Arduino 板→Arduino API，裸 MCU→寄存器）。
> - **工具链增强**：BuildProvider 支持 Arduino Core 自动检测与链接（24 源文件，avr-g++ 编译），寄存器级代码向后兼容。
> **2026-07-18 CH340 串口驱动兼容策略铁证定案**（新增 §4.4 + 长期记忆 MEMORY.md §10）：确认 CH340 3.5 正常 / 3.9+4.0 驱动 SetCommState 同值 GEN_FAILURE(31)。确立三层 pyserial 优先 + Win32Serial toggle fallback 自适应策略（STC-ISP 式"不挑驱动"）。实测 3.5/3.9/4.0 三版驱动 E2E 全通过。回收过度设计（删除 toggle 主导的 ComPort、_win32_port_reset、S5 冗余 sleep、S6 波特率预切换）；Win32Serial 降为 fallback 模块；恢复 _bootloader_reset 作双用途（bootloader + 残留清理）。265 测试无回归，外部工具同值失败为驱动自身问题已验证。
