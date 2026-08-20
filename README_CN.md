# FirmForge

> **中文** · [English（README.md）](README.md)
>
> 本仓库与 GitHub 仓库 `github.com/NotchStone/firmforge` 内容同步。

FirmForge 是基于 MCP 和 CLI 的 MCU 固件验证工具链，面向 AI 编码 Agent 的嵌入式开发流程。工具链提供五阶段硬件流水线——Detect（识别）、Review（审查）、Build（编译）、Flash（烧录）、Verify（验证），并通过 MCP 和 CLI 工具（`ff_detect`、`ff_context`、`ff_build`、`ff_run`、`ff_flash`、`ff_monitor`）向 Agent 开放各阶段能力。

固件由 avr-gcc / ArduinoCore-avr 真实编译，avrdude 烧录，串口回读验证。不承担代码生成职能。

## 流水线

| 阶段 | 说明 | 失败处理 |
|:--|:--|:--|
| S1 Detect | avrdude 芯片签名探测识别板卡；USB VID/PID 与工作区推断兜底 | 阻断 |
| S2 Review | 静态分析：cppcheck、寄存器/位域与芯片知识库比对、置信度评分 | 不阻断 |
| S3 Build | 编译为 firmware.hex：裸寄存器 C（avr-gcc，`-std=c11`）或 Arduino API（ArduinoCore-avr）；SHA256 指纹缓存 | 阻断 |
| S4 Flash | avrdude 烧录（ATmega2560 使用 `-D` 跳过芯片擦除）+ bootloader 复位 | 阻断 |
| S5 Verify | 串口回读与模式匹配；浏览器实时面板 | 不阻断 |

## 支持目标

| 板卡 | MCU | 说明 |
|:--|:--|:--|
| `arduino_mega` | ATmega2560 | 知识库 202 个寄存器（含 GCC 别名） |
| `arduino_328p` | ATmega328P（UNO/Nano） | 知识库 91 个寄存器 |

自定义板卡通过 `--boards-dir` 支持。

## 安装

要求：Python ≥ 3.10。仅 Flash 与 Verify 阶段需要硬件。

```bash
pip install git+https://gitee.com/notchstone/firmforge.git
ff setup
```

`ff setup` 将 avr-gcc、avrdude、cppcheck、ArduinoCore-avr 下载安装至 `~/.firmforge/`，可重复执行。

MCP 支持（Agent 集成）：

```bash
pip install "firmforge[mcp] @ git+https://gitee.com/notchstone/firmforge.git"
```

稳定版 wheel 附于 GitHub Release：`github.com/NotchStone/firmforge/releases`。

## 使用

```bash
# 识别已连接板卡
ff detect

# 审查 + 编译（无需硬件）
ff build arduino_mega --app path/to/source

# 硬件全链路
ff run arduino_mega --app path/to/source --expected "Hello World"

# 直烧 hex
ff flash arduino_mega --firmware firmware.hex
```

## MCP 服务器

向 Agent（CodeBuddy / Cursor / Claude Desktop 等）注册：

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

自然语言输入需求，Agent 工作流编写代码后使用 `ff_run` 完成编译、烧录与验证。内置数据（板卡定义、芯片知识、工具链清单）随包解析，服务器可在任意工作目录运行。

## 开发

```bash
pip install -e .[test,mcp]
pytest
```

## 许可证

MIT © FirmForge Contributors
