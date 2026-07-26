# FirmForge LLM 代码生成技术路线分析

> 日期：2026-07-12
> 议题：LLM 代码生成应采用"知识库约束生成"还是"自由生成+后验证"？
> 状态：待评审决策

---

## 一、两条技术路线定义

### 路线 A：知识库约束生成（Constraint-First）

**核心思路**：LLM 只能使用知识库中索引的原厂 API / 寄存器定义。生成阶段就排除"不存在的函数"和"幻觉寄存器"。

```
用户意图 → RAG 检索可用 API/寄存器 → 约束 prompt（白名单）→ LLM 在白名单内生成
```

- 知识库 = 允许列表（allow-list）
- 生成前：LLM 看到的 prompt 只包含合法 API
- 生成后：编译验证（语法兜底）
- 类比：白名单防火墙

### 路线 B：自由生成+后验证（Generation-First + Post-Verification）

**核心思路**：LLM 在规则约束下（代码风格、安全规则）自由生成代码，生成后通过 Citation Gate、编译、HIL 测试多道闸门拦截错误。

```
用户意图 → 规则 prompt（风格+安全） → LLM 自由生成 → Citation Gate → 编译 → 烧录 → HIL 验证
```

- 知识库 = 验证基准（ground-truth），不限制生成
- 生成前：LLM 看到参考文档但可自由选择写法
- 生成后：Citation Gate 校验引用 + 编译验证语法 + HIL 验证行为
- 类比：入侵检测系统（IDS）

---

## 二、业界对标

### 2.1 通用 AI 编程工具（Copilot / Cursor / Codeium）

| 产品 | 路线 | 关键机制 |
|------|------|---------|
| GitHub Copilot | B（自由+后验证） | LLM 自由生成 → Linter → 测试反馈 → agent loop 修复 |
| Cursor Composer | B（自由+后验证） | 多文件自由生成 → 编译 → 读错误 → 重写 |
| Codeium Cascade | B（自由+后验证） | agentic loop: 生成→运行→修正 |

**共识**：通用领域 LLM 能力强、工具链成熟，约束解码牺牲灵活性，不值得。

### 2.2 嵌入式 AI 工具

| 产品 | 路线 | 关键机制 |
|------|------|---------|
| Embedder | **A+B 混合** | Datasheet 约束生成 + build/flash/test 硬件验证闭环 |
| PicoClaw | 工具层 A | `allowed_commands` 白名单约束工具调用 |

**Embedder 是当前嵌入式 AI 编程标杆**，采用"约束生成 + 硬件验证"双保险：
- 每行代码标注引用的参考手册章节（约束）
- 无幻觉寄存器、无虚构时钟树（约束）
- 真实调试探针验证行为（后验证）

### 2.3 学术研究

| 研究 | 发现 |
|------|------|
| SemGuard (ASE 2025) | LLM 代码错误中 **>60% 是语义错误**（能编译但行为错）——post-hoc 验证的主要盲区 |
| SCodeGen (TrustCom 2025) | constrained decoding 在语法/安全约束上 **>99% 有效**，比 post-hoc 高 20% |
| 微信 ICSME'25 | BM25+GTE RAG 表现最优，属 retrieval-**augmented**（增强而非约束） |

**关键发现**：纯 post-hoc 验证有 60% 的语义错误盲区——代码能编译、能烧录，但行为不对。这正是嵌入式领域的致命风险。

---

## 三、FirmForge 场景适配分析

### 3.1 领域特性

| 维度 | FirmForge 场景 | 影响 |
|------|---------------|------|
| 安全风险 | 高（直接操作硬件，错误可能烧板） | 倾向约束 |
| 测试覆盖 | 低（HIL 只能验证串口输出，无法验证寄存器级行为） | 倾向约束 |
| LLM 能力 | 强（直接寄存器操作代码质量已验证足够好） | 倾向自由 |
| 知识库完整度 | 中（AVR GPIO+USART 覆盖，其他外设未覆盖） | 约束有盲区 |
| 扩展性 | 多 MCU（Arduino/STM32/ESP32），API 差异大 | 约束维护成本高 |

### 3.2 路线 A 优劣

**优势**：
- 从源头消除幻觉寄存器（生成阶段就不可能写出 `PORTZ`）
- 符合安全关键领域最佳实践（对标 Embedder）
- Citation Gate 变成"确认"而非"发现"——生成时就保证合法

**劣势**：
- **知识库不完整 = 约束不完整**：当前只覆盖 GPIO+USART，Timer/SPI/I2C/ADC 未覆盖。约束模式下，LLM 不能用未索引的 API，即使该 API 是合法的
- **限制 LLM 创造力**：复杂任务可能需要组合多个 API，白名单限制了表达空间
- **维护成本高**：每个 MCU 系列都要维护完整的 API 白名单。STM32 的 HAL 库有上千个函数
- **分布偏置风险**：学术研究表明，过度约束会导致 LLM 输出"语法对但语义怪"的代码
- **与"封装最小化"原则冲突**：Arduino 原厂 API 已 AI 友好，不需要额外约束层

### 3.3 路线 B 优劣

**优势**：
- **LLM 发挥空间大**：可自由选择最优写法（Arduino API / 寄存器 / 混合）
- **知识库不完整时不阻塞**：LLM 可以用知识库未覆盖的 API，编译验证兜底
- **扩展性好**：新 MCU 只需加 board.json + 参考库，不改生成约束
- **与现有架构一致**：Citation Gate + Confidence + COMPILE_FIX_LOOP 已就位
- **符合通用 AI 编程工具主流路线**（Copilot/Cursor）

**劣势**：
- **语义错误盲区**：60% 的错误是"能编译但行为错"，Citation Gate 只校验寄存器名存在性，不校验用法正确性
- **HIL 验证有限**：当前只能验证串口输出，无法验证 GPIO 电平、时序、中断行为
- **依赖编译器质量**：avr-gcc 的警告/错误信息质量决定修复闭环效率

### 3.4 失败模式对比

| 失败类型 | 路线 A 能否拦截 | 路线 B 能否拦截 |
|---------|----------------|----------------|
| 幻觉寄存器（PORTZ） | ✅ 生成时拦截 | ✅ Citation Gate 拦截 |
| 错误寄存器用法（写只读寄存器） | ❌ 白名单不包含用法 | ❌ Citation Gate 不校验用法 |
| 错误波特率值（UBRR=999） | ❌ 白名单不含值约束 | ⚠️ Confidence 评分部分覆盖 |
| 语义错误（LED 闪错频率） | ❌ | ❌ HIL 无法验证 |
| API 参数错误（pinMode(13, 5)） | ❌ 白名单不含参数 | ⚠️ API contract 有 params 约束但未集成 |
| 编译错误（语法错） | ✅ 编译兜底 | ✅ 编译拦截 |

**关键洞察**：两条路线对"语义错误"都无能为力。路线 A 在"幻觉寄存器"上有优势，但路线 B 的 Citation Gate 已经覆盖了这个场景。

---

## 四、推荐路线：分层混合（Hybrid Layered）

**不在 A 和 B 之间二选一，而是按层次组合。**

### 4.1 三层架构

```
┌─────────────────────────────────────────────────┐
│  Layer 1: 规则约束（soft constraint）            │
│  - code_style: arduino_api | avr_register       │
│  - 安全规则（ISR 禁阻塞等）                      │
│  - 知识库 API/寄存器参考作为"推荐"注入 prompt     │
│  → LLM 自由生成，但知道应该用什么风格             │
├─────────────────────────────────────────────────┤
│  Layer 2: 引用验证（hard gate）                  │
│  - Citation Gate: 寄存器/位域必须可解析          │
│  - 不可解析 → 阻断编译                           │
│  → 拦截幻觉寄存器（路线 A 的核心价值）            │
├─────────────────────────────────────────────────┤
│  Layer 3: 行为验证（empirical）                  │
│  - 编译验证（语法）                              │
│  - HIL 串口验证（行为）                          │
│  - Confidence 评分（置信度）                     │
│  - COMPILE_FIX_LOOP（自动修复）                  │
│  → 拦截语法错误和部分行为错误                     │
└─────────────────────────────────────────────────┘
```

### 4.2 核心设计决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| 知识库角色 | **验证基准**（非白名单） | 知识库不完整时不阻塞生成；验证阶段拦截幻觉 |
| code_style | **board.json 驱动** | Arduino 板 → Arduino API；裸 MCU → 寄存器操作 |
| LLM 自由度 | **规则约束 + 自由生成** | 安全规则是硬约束，代码风格是软约束，API 选择自由 |
| 验证深度 | **Citation + Compile + HIL** | 多层闸门，各管一段 |
| 知识库扩展 | **渐进式** | 先覆盖高频外设，未覆盖的外设靠编译兜底 |

### 4.3 与原架构的变更

| 原设计 | 变更后 | 变更性质 |
|--------|--------|---------|
| "只使用原厂库函数编程" | "自由生成 + Citation Gate 验证" | **架构变更**：约束→验证 |
| CodeGenerator prompt 不区分风格 | board.json `code_style` 驱动 | **新增**：风格字段 |
| 知识库 = 允许列表 | 知识库 = 验证基准 | **语义变更**：allow-list → ground-truth |
| Citation Gate = 生成后检查 | Citation Gate = 生成后检查（不变） | 无变更 |
| 无 API 参数校验 | API contract params 约束（P1 增强） | **未来增强** |

### 4.4 对标 Embedder 的差异

| 维度 | Embedder | FirmForge（推荐路线） |
|------|---------|---------------------|
| 生成约束 | 硬约束（datasheet 引用必须存在） | 软约束（风格规则）+ 硬验证（Citation Gate） |
| 验证手段 | 调试探针寄存器回读 | 串口 HIL + Citation Gate + 编译 |
| 知识库完整度要求 | 高（必须完整才能约束） | 中（不完整时降级为编译兜底） |
| 多 MCU 扩展 | 按 MCU 维护完整 datasheet 索引 | 按 MCU 维护参考库，验证而非约束 |

**FirmForge 的差异化**：知识库不完整时不阻塞（降级为编译兜底），而 Embedder 要求知识库必须完整。这降低了多 MCU 扩展的维护成本。

---

## 五、实施路径

### 5.1 立即可做（今天）

1. **board.json 加 `code_style` 字段**
   - `arduino_mega`: `"code_style": "arduino_api"`
   - `stm32f103vet6_minisys`: `"code_style": "stm32_hal"`

2. **CodeGenerator prompt 根据 code_style 调整**
   - `arduino_api`: prompt 强调"使用 pinMode/digitalWrite/Serial 等 Arduino API"
   - `avr_register`: prompt 强调"使用 DDRB/PORTB/UCSR0B 等寄存器操作"
   - `stm32_hal`: prompt 强调"使用 HAL_GPIO_WritePin 等 HAL 库函数"

3. **工具链支持 Arduino 核心库**（解决 .ino 编译问题）
   - 安装 Arduino AVR Core（LGPL，免费）
   - BuildProvider 链接 Arduino 核心 `.a` 文件
   - 或：生成 `.c` 文件但 `#include <Arduino.h>` + 链接核心库

### 5.2 短期（阶段 4 内）

4. **API 参数校验增强**：Citation Gate 不仅校验寄存器名，还校验 API 参数范围（如 `pinMode` 的 mode 只能是 INPUT/OUTPUT/INPUT_PULLUP）
5. **Confidence 评分增强**：加入 API 参数合理性评分

### 5.3 中期（阶段 5+）

6. **硬件信号回灌**：OpenOCD/GDB 寄存器回读，补上"语义错误"盲区
7. **完整知识库**：覆盖 Timer/SPI/I2C/ADC 等外设

---

## 六、结论

**推荐路线 B + Layer 2 硬验证 = 分层混合路线。**

理由：
1. 知识库不完整时不阻塞生成（路线 B 的核心优势）
2. Citation Gate 已验证能拦截幻觉寄存器（Layer 2 的核心价值）
3. 符合业界主流（通用工具走 B，嵌入式加验证层）
4. 多 MCU 扩展成本低（只需加参考库，不改生成约束）
5. LLM 创造力不受限（复杂任务能自由组合 API）

**不选路线 A 的关键原因**：知识库完整度不足时，约束模式会阻塞合法的 API 使用。在多 MCU 扩展阶段，每个新 MCU 都需要完整的 API 白名单，维护成本不可接受。

**路线 A 的价值不否定**：在安全关键场景（医疗/汽车），知识库完整时，路线 A 的"源头消除"比"事后拦截"更可靠。FirmForge 可在未来为安全关键板级配置 `strict_mode: true` 启用约束生成。
