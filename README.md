# FirmForge

**Multi-MCU firmware verification toolchain** — Review → Build → Flash → Verify on real hardware.

FirmForge is the verification half of an AI-assisted MCU development workflow: an AI coding agent writes the firmware, FirmForge compiles it against a real toolchain, flashes it to the board, and verifies the serial output. It does **not** generate code — it is the trustworthy backstop between "the agent said it works" and "the hardware actually works".

```
Detect → Review → Build → Flash → Verify
```

| Stage | What it does | Blocks on failure? |
|:--|:--|:--|
| S1 Detect | Identify board via avrdude chip signature probe (USB VID/PID + workspace inference as fallback) | Yes |
| S2 Review | Static scan: Cppcheck + register/bitfield reference check + confidence scoring | No (warning) |
| S3 Build | avr-gcc compile (bare-register C) or Arduino API (ArduinoCore-avr), cache-accelerated | Yes |
| S4 Flash | avrdude programming (Mega uses `-D` skip-chip-erase) with bootloader reset | Yes |
| S5 Verify | Serial readback, expected-pattern match, live browser panel | No |

## Features

- **Dual compile routes**: bare-register C (`avr-gcc -std=c11`) and Arduino API (`.ino`/`#include <Arduino.h>` with bundled ArduinoCore-avr) — auto-routed by source content
- **Chip knowledge base**: ATmega2560 (202 registers incl. GCC aliases), ATmega328P (91 registers); register hallucination check before compile
- **Incremental pipeline**: SHA256 fingerprints of source/hex/port/board drive stage skipping (cold core build ~55s → warm ~3s)
- **Live serial panel**: browser-based Serial + Modbus RTU (FC03/04/06/16) debugging with frame decode
- **MCP server**: expose `ff_detect / ff_context / ff_build / ff_run / ff_flash / ff_monitor` to AI agents (CodeBuddy, Cursor, Claude Desktop, ...)
- **Toolchain auto-install**: `ff setup` downloads avr-gcc/avrdude manifests to `~/.firmforge/toolchains`

## Install

```bash
pip install firmforge            # or: pip install firmforge[mcp] for agent integration
ff setup                         # download toolchains (avr-gcc, avrdude) on first use
```

> Requires Python ≥ 3.10. Windows / macOS / Linux. Hardware needed only for Flash/Verify stages.

## Quick Start

```bash
# 1. Detect connected board
ff detect

# 2. Compile only (CI-safe, no hardware)
ff build arduino_mega --app path/to/source

# 3. Full pipeline on hardware
ff run arduino_mega --app path/to/source --expected "Hello World"

# 4. Flash a pre-built hex
ff flash arduino_mega --firmware firmware.hex
```

Supported boards (bundled definitions): `arduino_mega` (ATmega2560), `arduino_328p` (UNO/Nano, ATmega328P). Bring your own board via `--boards-dir`.

## MCP / AI Agent Integration

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

Agent workflow: `ff_context` (read registers/pins before writing code) → write firmware → `ff_run` (compile+flash+verify). Works from any directory — all bundled data lives inside the package.

## Development

```bash
pip install -e .[test,mcp]
pytest
```

## License

MIT © FirmForge Contributors
