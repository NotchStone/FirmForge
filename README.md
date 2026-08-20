# FirmForge

> **English** · [中文（README_CN.md）](README_CN.md)

FirmForge is an MCP-based firmware verification toolchain for MCU development with AI coding agents. It provides a five-stage hardware pipeline — Detect, Review, Build, Flash, Verify — and exposes the stages to agents as MCP tools (`ff_detect`, `ff_context`, `ff_build`, `ff_run`, `ff_flash`, `ff_monitor`).

The toolchain compiles firmware with a real compiler (avr-gcc / ArduinoCore-avr), programs the target with avrdude, and verifies the result via serial readback. Code generation is out of scope.

## Pipeline

| Stage | Description | Failure handling |
|:--|:--|:--|
| S1 Detect | Board identification via avrdude chip-signature probe; USB VID/PID and workspace inference as fallbacks | Blocking |
| S2 Review | Static analysis: cppcheck, register/bitfield validation against the chip knowledge base, confidence scoring | Non-blocking |
| S3 Build | Compile to firmware.hex: bare-register C (avr-gcc, `-std=c11`) or Arduino API (ArduinoCore-avr); SHA256-fingerprint caching | Blocking |
| S4 Flash | avrdude programming (ATmega2560 uses `-D` skip-chip-erase) with bootloader reset | Blocking |
| S5 Verify | Serial readback with pattern matching; live browser panel | Non-blocking |

## Supported Targets

| Board | MCU | Notes |
|:--|:--|:--|
| `arduino_mega` | ATmega2560 | 202 registers in knowledge base (incl. GCC aliases) |
| `arduino_328p` | ATmega328P (UNO/Nano) | 91 registers in knowledge base |

Custom boards are supported via `--boards-dir`.

## Installation

Requirements: Python ≥ 3.10. Hardware is required only for the Flash and Verify stages.

```bash
pip install git+https://github.com/NotchStone/firmforge.git
ff setup
```

`ff setup` downloads and installs avr-gcc, avrdude, cppcheck, and ArduinoCore-avr to `~/.firmforge/`. Re-running is idempotent.

For MCP support (agent integration):

```bash
pip install "firmforge[mcp] @ git+https://github.com/NotchStone/firmforge.git"
```

Stable wheels are attached to [GitHub Releases](https://github.com/NotchStone/firmforge/releases).

A China mirror is available on Gitee: see [README_CN.md](README_CN.md) (中文).

## Usage

```bash
# Detect connected board
ff detect

# Review + compile only (no hardware required)
ff build arduino_mega --app path/to/source

# Full pipeline on hardware
ff run arduino_mega --app path/to/source --expected "Hello World"

# Flash a pre-built hex
ff flash arduino_mega --firmware firmware.hex
```

## MCP Server

Register the server with your agent (CodeBuddy, Cursor, Claude Desktop, ...):

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

Agent workflow: query `ff_context` for register/pin references before writing firmware, then `ff_run` to compile, flash, and verify. Bundled data (board definitions, chip knowledge, toolchain manifests) is resolved from inside the package; the server runs from any working directory.

## Development

```bash
pip install -e .[test,mcp]
pytest
```

## License

MIT © FirmForge Contributors
