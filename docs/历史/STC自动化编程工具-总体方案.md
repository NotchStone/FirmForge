# STC 51 系列单片机自动化编程生产工具 —— 总体方案

> 版本：v1.0  日期：2026-07-05
> 自动化执行内核：Codebuddy（Skill + MCP 机制）
> 目标芯片：STC Ai8051U / STC8H8K64U / STC32G12K128
> 设计原则：高内聚、低耦合的模块化设计；边开发、边测试的模块化测试

---

## 一、项目目标

搭建一套面向 STC 51 系列单片机的**自动化编程生产工具链**，以 Codebuddy 为自动化执行内核，打通"需求 → 代码生成 → 编译 → 烧录 → 测试验证"的全流程自动化闭环，覆盖三款目标芯片：

| 芯片 | 内核 | 位宽模式 | 编译器 | 定位 |
|------|------|----------|--------|------|
| STC8H8K64U | 8051 | 8 位 | Keil C51 | 8 位高性能主流 |
| STC32G12K128 | 251 扩展 | 32 位 | Keil C251 | 32 位高性能 |
| Ai8051U | 8051/251 | 8 位 / 32 位可切 | C51 / C251 | AI 增强 + USB |

**核心衡量标准**：能用一句话（自然语言）驱动 Codebuddy 完成"生成指定外设驱动 → 编译 → 烧录到指定开发板 → 串口回传测试结果 → 自动判定 PASS/FAIL"的完整闭环。

---

## 二、现有条件与资源盘点

### 2.1 硬件
- STC Ai8051U 开发板（支持 USB，8/32 位双模式）
- STC8H8K64U 开发板（UART ISP）
- STC32G12K128 开发板（32 位，UART/USB ISP）

### 2.2 官方在线资源

| 资源 | 地址 | 形态 | 自动化价值 |
|------|------|------|------------|
| 官方 AI 助手 | https://help.stcaimcu.com/ | 门户 | 背景资料 |
| 数据手册 MCP | https://help.stcaimcu.com/mcp | MCP over SSE | **高**：6 个工具，手册/论坛查询 |
| Web-ISP 烧录 | https://help.stcaimcu.com/isp | WebUSB+WebSerial | 中：仅浏览器人工操作 |
| 库函数下载 | https://www.stcai.com/khs | ZIP 包 | **高**：三款芯片均有库 |

### 2.3 官方数据手册 MCP 详情
- 协议：MCP over SSE（流式 HTTP）
- Server URL：`https://help.stcaimcu.com/mcp`
- 工具（6 个）：
  1. `list_files` — 列出所有可用数据手册文件
  2. `list_chapters` — 列出手册章节目录
  3. `query_section` — 按标题查询手册正文（含寄存器表）
  4. `search_keyword` — 章节内关键词搜索定位
  5. `search_forum` — 搜索 STC 论坛
  6. `read_forum_post` — 读取论坛帖子详情
- 限制：**30 分钟 / 40 次**（按 session 计数，超限返回 429）→ 必须本地缓存

### 2.4 官方库函数资源

| 库包 | 覆盖芯片 | 下载 |
|------|----------|------|
| STC32G 库函数 | STC32G12K128 等 | STC32G-SOFTWARE-LIB.zip |
| STC8G/8H 库函数 | STC8H8K64U 等 | STC8G-STC8H-LIB-DEMO-CODE.zip |
| Ai8051U 创新风格库（32/8 位） | Ai8051U | AI8051U 专用库函数.zip |
| Ai8051U 传统风格库 | Ai8051U | AI8051U-SOFTWARE-LIB.zip |
| USB 库 | 带硬件 USB 的芯片 | STC_USB_LIBRARY.zip |
| MDU/TFPU/DSP 数学库 | 各系列硬件运算单元 | 分型号 .LIB 文件 |

---

## 三、技术路线分析

### 3.1 编译工具链

**主选方案：Keil 命令行编译**

| 芯片 | 编译器 | 工程类型 | 命令行入口 |
|------|--------|----------|------------|
| STC8H8K64U | Keil C51 | .uvproj (C51) | `UV4 -b proj.uvproj -o build.log` |
| STC32G12K128 | Keil C251 | .uvproj (C251) | `UV4 -b proj.uvproj -o build.log` |
| Ai8051U (8 位) | Keil C51 | .uvproj (C51) | 同上 |
| Ai8051U (32 位) | Keil C251 | .uvproj (C251) | 同上 |

- 返回码：0 = 成功，1 = 警告，≥2 = 错误
- 自动化要点：解析 `build.log` 提取错误/警告行，定位文件:行号，反馈给 Codebuddy 自动修复
- 已验证可行性：UV4 命令行编译是 Keil 官方支持的无 GUI 编译方式，社区有成熟自动化脚本（keil-autopiler 等）

**备选方案：SDCC（仅 8 位）**
- 开源，支持 8051 内核，可覆盖 STC8H8K64U 与 Ai8051U 8 位模式
- **不支持 C251 架构**，无法覆盖 STC32G12K128 与 Ai8051U 32 位模式
- 仅作为 Keil 不可用时的 8 位降级方案

> 决策：以 Keil C51/C251 命令行为主线；SDCC 作为 8 位开源备选；编译层抽象为统一 `build` 接口，后端可切换。

### 3.2 烧录工具链（关键风险点）

**核心矛盾**：官方 STC-ISP 软件**仅 GUI、无命令行模式**（已确认）；Web-ISP 仅浏览器人工操作。自动化烧录必须依赖第三方或自研。

**开源方案：stcgal（grigorig/stcgal）**
- 支持：STC 89/90/10/11/12/15/**8/32** 系列，UART + USB BSL
- 自动电源循环（DTR toggle）、自动协议检测
- 三款芯片支持情况：

| 芯片 | stcgal 支持 | 说明 |
|------|-------------|------|
| STC8H8K64U | ✅ UART ISP | 属 8 系列，已验证支持 |
| STC32G12K128 | ✅ UART ISP | 属 32 系列，需用最新 stcgal 验证 |
| Ai8051U | ⚠️ 不支持 USB BSL | 官方论坛确认 stcgal 未适配 Ai8051U 的 USB 协议；UART 可行性需验证 |

**Ai8051U 烧录应对策略（按优先级）：**
1. **方案 A（优先）**：验证 Ai8051U 的 UART ISP 是否可用 stcgal 的 STC8 协议烧录。Ai8051U 保留传统串口下载能力，若协议兼容则直接复用 stcgal。
2. **方案 B**：自研 Python 烧录工具，基于 pyserial 逆向/参考 Ai8051U BSL 协议（可借助官方 MCP 查询手册中的 ISP 协议章节 + 论坛讨论）。
3. **方案 C（兜底）**：浏览器自动化 Web-ISP（Playwright + WebSerial），笨重但可用，仅作应急。

> 决策：烧录层抽象为统一 `flash` 接口，按芯片自动选择后端（stcgal / 自研工具）；Ai8051U 列为阶段 3 专项攻坚。

### 3.3 手册查询与代码生成（MCP）

- **直接接入官方数据手册 MCP**（SSE 协议，零开发成本）
- 因 30min/40 次速率限制，**必须做本地缓存**：查询结果落盘为 `docs/cache/manual/`，命中缓存不消耗配额
- 代码生成流程：`查手册(MCP) → 选库函数模板 → 生成驱动 .c/.h → 生成对应测试`

### 3.4 测试方案（边开发边测试）

单片机资源受限，无法跑重型测试框架，采用**轻量断言 + 串口回传 + 主机判定**三层：

| 层级 | 方法 | 工具 |
|------|------|------|
| 单元层 | 函数级，主机端 mock 寄存器 | Python mock + C 函数桩 |
| 模块层 | 硬件在环，串口输出断言 | 自研 `assert` 宏 + 串口收集 |
| 系统层 | 自动化测试用例矩阵 | 主机端 `collect.py` 自动判定 |

- 单片机端断言宏：`ASSERT(cond)` → 失败时串口打印 `TEST_FAIL: file:line:cond`，成功打印 `TEST_PASS: module`
- 主机端 `collect.py`：监听串口，解析 PASS/FAIL，汇总报告
- **边开发边测试**：每个外设驱动模块开发完成 → 立即生成测试固件 → 烧录 → 收集结果 → 通过才进入下一模块

---

## 四、整体架构设计（分层 + 模块化）

```
┌─────────────────────────────────────────────────┐
│  自动化层 (Codebuddy)                            │
│  Skill: scaffold/manual/driver-gen/build/flash/test/app-gen │
│  MCP: 官方数据手册 MCP + 本地工具链 MCP(可选)     │
│  规则: .workbuddy/ 项目规则 + 编码/测试规范       │
└─────────────────────────────────────────────────┘
                       │ 驱动
┌─────────────────────────────────────────────────┐
│  工具链层 (Toolchain)                            │
│  编译: Keil C51/C251 命令行 (UV4)                │
│  烧录: stcgal / 自研工具 (统一 flash 接口)        │
│  测试: assert 宏 + 串口 collect.py               │
│  缓存: 手册查询本地缓存                          │
└─────────────────────────────────────────────────┘
                       │ 产出
┌─────────────────────────────────────────────────┐
│  应用层 (Application)   用户业务代码              │
├─────────────────────────────────────────────────┤
│  驱动层 (Driver/HAL)    GPIO/UART/ADC/Timer/...  │
├─────────────────────────────────────────────────┤
│  板级层 (BSP)           芯片配置/时钟/引脚映射    │
├─────────────────────────────────────────────────┤
│  Vendor 层              官方库函数 + 头文件       │
└─────────────────────────────────────────────────┘
```

**模块化边界（高内聚低耦合）：**
- 驱动层只依赖 Vendor 层头文件，不依赖应用层
- 应用层通过驱动层标准接口调用，不直接碰寄存器
- BSP 层隔离芯片差异，驱动层通过 BSP 抽象宏访问硬件
- 工具链层与代码层完全解耦，可独立替换

---

## 五、Skill 开发清单

| # | Skill 名称 | 职责 | 关键能力 |
|---|-----------|------|----------|
| 1 | `stc-project-scaffold` | 工程脚手架 | 按芯片生成目录结构、Keil 工程(.uvproj)、build/flash 脚本、多 target 配置 |
| 2 | `stc-manual` | 手册查询 | 封装官方 MCP，带本地缓存（规避 40 次/30min 限制），提供查寄存器/查外设/查论坛 |
| 3 | `stc-driver-gen` | 驱动代码生成 | 选芯片→查手册→套库函数模板→生成 driver.c/.h + 对应 test.c |
| 4 | `stc-build` | 编译构建 | 选芯片 target→调 UV4 命令行→解析日志→报错自动定位修复 |
| 5 | `stc-flash` | 烧录 | 选芯片→选后端(stcgal/自研)→自动检测串口→烧录 hex |
| 6 | `stc-test` | 硬件在环测试 | 烧录测试固件→串口收集→断言判定→输出报告 |
| 7 | `stc-app-gen` | 应用生成 | 组合多个驱动生成应用示例（如"UART 回显+ADC 采集"） |

**Skill 依赖关系：**
```
scaffold ──► manual ──► driver-gen ──► build ──► flash ──► test
                                   └─► app-gen ──┘
```

---

## 六、MCP 配置方案

### 6.1 直接接入（官方，零开发）
写入 `~/.workbuddy/mcp.json`：
```json
{
  "mcpServers": {
    "stc-manual": {
      "type": "sse",
      "url": "https://help.stcaimcu.com/mcp"
    }
  }
}
```
接入后在 Codebuddy 连接器管理页"信任"该 server 即可使用 6 个工具。

### 6.2 可选自研（本地工具链 MCP）
若希望编译/烧录/测试也以 MCP 工具形式暴露（而非 Skill 内 Bash 调用），可自研 stdio 本地 MCP，封装：
- `build_project(chip, target)` → 调 UV4
- `flash_chip(chip, port, hex)` → 调 stcgal/自研
- `run_test(chip, port)` → 烧录测试固件 + 串口收集
- `query_manual_cached(query)` → 带缓存的官方 MCP 代理

> 决策：阶段 1-2 用 Skill + Bash 调用快速跑通；阶段 5 若需稳定 CI，再封装为本地 MCP。

---

## 七、项目规则与规范

### 7.1 目录结构规范
```
MCU/
├── docs/                    # 方案、手册缓存、文档
│   └── cache/manual/        # MCP 查询本地缓存
├── vendor/                  # 官方库函数（不修改）
│   ├── stc8h/
│   ├── stc32g/
│   └── ai8051u/
├── bsp/                     # 板级配置（时钟/引脚映射）
│   ├── stc8h8k64u/
│   ├── stc32g12k128/
│   └── ai8051u/
├── drivers/                 # 驱动层（高内聚，每外设一模块）
│   ├── gpio/
│   ├── uart/
│   ├── adc/
│   ├── timer/
│   ├── pwm/
│   ├── i2c/
│   ├── spi/
│   └── usb/
├── apps/                    # 应用层
├── tests/                   # 测试固件 + 用例
├── tools/                   # 自动化脚本
│   ├── build.py
│   ├── flash.py
│   ├── collect.py
│   └── install_toolchain.sh
├── projects/                # Keil 工程（每芯片每应用一个 .uvproj）
└── .workbuddy/
    ├── skills/              # 项目级 Skill
    └── memory/              # 项目记忆
```

### 7.2 编码规范
- 文件命名：`{module}_{chip}.c`（如 `uart_stc8h.c`）或芯片无关则 `uart.c` + 条件编译
- 函数命名：`{module}_{action}`（如 `uart_init`, `adc_read`）
- 头文件接口隔离：驱动只暴露 `.h` 接口，内部寄存器操作封装在 `.c`
- 条件编译：用 `#ifdef CHIP_STC8H / CHIP_STC32G / CHIP_AI8051U` 隔离芯片差异
- **禁止**应用层直接读写寄存器，必须走驱动接口

### 7.3 编译配置规范
- 每芯片独立 Keil target，输出到 `build/{chip}/`
- 工程路径**不含中文和空格**（Keil 命令行要求）
- 编译宏定义：`-DCHIP_STC8H` 等，驱动据此条件编译

### 7.4 测试规范（边开发边测试）
- 每个驱动模块必须配套 `test_{module}.c`，含 `TEST_PASS/TEST_FAIL` 串口输出
- 测试固件独立 target，烧录后串口自动回传结果
- 驱动开发完成 → 立即编译 → 烧录测试 → PASS 才合并
- 测试用例纳入 `tests/`，可批量回归

---

## 八、基础设施清单

| # | 基础设施 | 说明 |
|---|---------|------|
| 1 | 工具链安装脚本 | 检测/安装 Keil 路径、pip install stcgal、Python venv |
| 2 | 库函数管理 | `tools/fetch_vendor.sh` 下载三套库 ZIP 到 vendor/，记录版本 |
| 3 | 编译自动化 | `tools/build.py {chip} {target}` 统一编译入口 |
| 4 | 烧录自动化 | `tools/flash.py {chip} {hex}` 芯片→后端自动映射 |
| 5 | 测试框架 | 单片机端 assert 宏 + 主机端 `tools/collect.py` 串口收集判定 |
| 6 | 串口日志 | pyserial 收发、日志解析、超时重试 |
| 7 | 本地 CI | `tools/ci.sh` 一键全量编译+烧录+测试+报告 |
| 8 | 手册缓存 | `stc-manual` skill 自动落盘查询结果 |
| 9 | 文档生成 | 从驱动注释 + 手册生成 API 文档 |

---

## 九、分阶段开发与测试计划

> 原则：每阶段产出可验证成果；边开发边测试；阶段末必须有人工验证点。

### 阶段 0：环境与基础设施搭建
- 安装 Keil C51 / C251（确认授权与路径）
- pip 安装 stcgal，Python 环境
- 下载三套官方库函数到 `vendor/`
- 建立项目目录骨架
- **验证点（人工）**：UV4 命令行编译官方例程成功；stcgal 烧录 STC8H8K64U 点灯成功
- **完成标志**：手动跑通一次"编译→烧录→点灯"

### 阶段 1：单芯片最小闭环（STC8H8K64U）
- 接入官方数据手册 MCP，验证 6 工具可用
- 开发 `stc-manual` skill（含本地缓存）
- 开发 `stc-project-scaffold` skill（STC8H target）
- 开发 `stc-build` skill（Keil C51 命令行 + 日志解析）
- 开发 `stc-flash` skill（stcgal 烧录 STC8H）
- 模块化测试：GPIO → UART → Timer，每个边开发边烧录测试
- 测试框架雏形：assert 宏 + collect.py
- **验证点（人工）**：Codebuddy 自动生成 GPIO 驱动 → 编译 → 烧录 → 串口回传 PASS
- **完成标志**：STC8H 单芯片全闭环自动化

### 阶段 2：扩展至 STC32G12K128
- `stc-project-scaffold` 扩展 STC32G target（Keil C251）
- `stc-build` 扩展 C251 命令行
- 验证 stcgal 对 STC32G12K128 烧录支持
- 适配 32 位库函数
- 复用测试框架，验证 32 位驱动
- **验证点（人工）**：STC32G 自动生成驱动 → 编译 → 烧录 → PASS
- **完成标志**：两款芯片（8 位 + 32 位）自动闭环

### 阶段 3：攻坚 Ai8051U 烧录（风险阶段）
- 通过 MCP 查询 Ai8051U ISP 协议章节 + 论坛讨论
- 验证 UART ISP 可行性（优先方案 A）
- 若需自研：开发 Python 烧录工具（方案 B）
- Ai8051U 库函数适配（8 位 / 32 位双模式）
- **验证点（人工）**：Ai8051U 自动烧录成功 + 双模式切换
- **完成标志**：三款芯片全部自动闭环

### 阶段 4：驱动库体系化与代码生成
- 完善 `stc-driver-gen` skill（多芯片多外设模板）
- 建立驱动模板库：GPIO/UART/ADC/Timer/PWM/I2C/SPI/USB
- 开发 `stc-app-gen` skill（组合驱动生成应用）
- 每外设独立测试用例，边开发边测
- **验证点（人工）**：一句话生成"UART 回显 + ADC 采集"应用并烧录验证
- **完成标志**：8 类外设驱动 + 应用生成可用

### 阶段 5：测试体系完善与本地 CI
- 完善 `stc-test` skill（自动化测试套件）
- 硬件在环测试矩阵：3 芯片 × N 外设
- （可选）封装本地工具链 MCP
- 本地 CI 脚本：一键全量编译 + 烧录 + 测试报告
- **验证点（人工）**：一键跑通全量测试，输出报告
- **完成标志**：CI 化回归测试

### 阶段 6：生产化与文档
- 工具链一键安装脚本
- 使用文档 + 开发规范
- Skill / MCP 打包复用
- **验证点（人工）**：全新环境一键搭建并跑通
- **完成标志**：可交付的生产工具

---

## 十、风险与应对

| 风险 | 等级 | 影响 | 应对 |
|------|------|------|------|
| Ai8051U 烧录无命令行工具 | 高 | 阶段 3 阻塞 | 优先 UART 验证 → 自研工具 → 浏览器兜底 |
| Keil 商业授权 | 中 | 编译受限 | 8 位用 SDCC 替代；32 位依赖 C251 授权 |
| MCP 速率限制（40次/30min） | 中 | 查询阻塞 | 本地缓存 + 批量查询 + 命中优先 |
| 硬件在环不稳定（串口/USB 干扰） | 中 | 测试误判 | 重试机制 + 超时处理 + 多次采样 |
| 多芯片编译器/库差异 | 中 | 维护成本 | 芯片隔离 target + 条件编译 + BSP 抽象 |
| stcgal 对 STC32G 支持未实测 | 低 | 烧录失败 | 阶段 2 优先验证，必要时补充协议适配 |

---

## 附：技术选型决策摘要

- **编译**：Keil C51/C251 命令行（UV4）为主，SDCC 为 8 位备选
- **烧录**：stcgal（STC8H/STC32G）+ 自研工具（Ai8051U），统一 flash 接口
- **手册**：官方 MCP 直连 + 本地缓存
- **测试**：轻量 assert + 串口回传 + 主机 collect.py 判定
- **自动化**：Codebuddy Skill 为主，本地 MCP 为辅
- **架构**：Vendor / BSP / Driver / App 四层 + 工具链层 + 自动化层
