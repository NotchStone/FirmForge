# FirmForge（Gitee 镜像版）

> 本文件为 **Gitee 镜像**专用说明。GitHub 主仓库见 [github.com/NotchStone/firmforge](https://github.com/NotchStone/firmforge)（英文 README）。

**给 AI 编码 Agent 使用的 MCU 固件验证 MCP 工具链** —— Detect → Review → Build → Flash → Verify 五阶段，真实硬件编译、烧录、串口回读验证。

AI Agent 写代码，FirmForge 负责证明代码真的能跑。它**不生成代码**，只做可信的后端守门员：Agent 说"能跑" → FirmForge 验证"确实能跑"。

```
Detect → Review → Build → Flash → Verify
```

| 阶段 | 功能 | 失败是否阻断 |
|:--|:--|:--|
| S1 Detect | avrdude 芯片签名探测识别板卡（USB VID/PID + 工作区推断兜底） | 阻断 |
| S2 Review | 静态扫描：Cppcheck + 寄存器/位域知识库查证 + 置信度评分 | 不阻断（警告） |
| S3 Build | avr-gcc 编译（裸寄存器 C）或 Arduino API（ArduinoCore-avr），缓存加速 | 阻断 |
| S4 Flash | avrdude 烧录（Mega 用 `-D` 跳过芯片擦除）+ bootloader 复位 | 阻断 |
| S5 Verify | 串口回读 + 期望模式匹配 + 浏览器实时面板 | 不阻断 |

## 功能特性

- **双编译路线**：裸寄存器 C（`avr-gcc -std=c11`）与 Arduino API（`.ino` / `#include <Arduino.h>`，内置 ArduinoCore-avr）——按源码内容自动路由
- **芯片知识库**：ATmega2560（202 个寄存器含 GCC 别名）、ATmega328P（91 个寄存器）；编译前做寄存器幻觉查证
- **增量流水线**：源码/hex/端口/板卡四指纹驱动阶段跳过（冷编译 ~55s → 热编译 ~3s）
- **浏览器调试面板**：串口实时监视 + Modbus RTU（FC03/04/06/16）帧解码
- **MCP 服务器**：`ff_detect / ff_context / ff_build / ff_run / ff_flash / ff_monitor` 六个工具，供 AI Agent（CodeBuddy / Cursor / Claude Desktop 等）直接调用
- **一键环境**：`ff setup` 自动下载 avr-gcc / avrdude / cppcheck / Arduino Core 到 `~/.firmforge/toolchains`

## 安装

**方式 A — pip 直装 Gitee 仓库**（推荐，国内网络友好）：

```bash
pip install git+https://gitee.com/notchstone/firmforge.git
pip install "firmforge[mcp] @ git+https://gitee.com/notchstone/firmforge.git"   # 带 MCP 支持
ff setup    # 首次使用自动下载工具链（avr-gcc, avrdude, cppcheck, Arduino Core）
```

**方式 B — Release wheel**（稳定版，随 GitHub Release 同步）：

```bash
pip install https://github.com/NotchStone/firmforge/releases/download/v0.2.0/firmforge-0.2.0-py3-none-any.whl
```

> 需要 Python ≥ 3.10。支持 Windows / macOS / Linux。仅 Flash/Verify 阶段需要硬件。

## 快速开始

```bash
# 1. 识别连接的板卡
ff detect

# 2. 仅编译（CI 安全，无需硬件）
ff build arduino_mega --app path/to/source

# 3. 硬件全链路
ff run arduino_mega --app path/to/source --expected "Hello World"

# 4. 直烧 hex
ff flash arduino_mega --firmware firmware.hex
```

内置板卡定义：`arduino_mega`（ATmega2560）、`arduino_328p`（UNO/Nano，ATmega328P）。自定义板卡用 `--boards-dir`。

## MCP / AI Agent 接入

```json
{
  "mcpServers": {
    "firmforge": {
      "command": "python",
      "args": ["-m", "firmforge.adapters.mcp_server"],
      "cwd": "/path/to/your/firmware/project"
    }
  }
}
```

Agent 工作流：先 `ff_context` 查寄存器/引脚参考 → 写固件 → `ff_run` 编译烧录验证。任意目录可运行——所有内置数据都随包携带。

## 开发

```bash
pip install -e .[test,mcp]
pytest
```

## 镜像同步说明

- **Gitee**（本镜像）：`gitee.com/notchstone/firmforge` —— 国内直连
- **GitHub**（主仓库）：`github.com/NotchStone/firmforge` —— 国际访问

两个仓库内容同步，功能一致。

## License

MIT © FirmForge Contributors
