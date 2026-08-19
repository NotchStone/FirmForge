# Contributing to FirmForge

Thanks for considering a contribution! This project keeps a few simple rules to stay healthy.

## How to contribute

1. **Open an issue first** for non-trivial changes — describe the problem and the intended fix before writing code.
2. **Fork + branch**: `feat/<name>` or `fix/<name>`.
3. **Keep commits focused**: one logical change per commit.
4. **Run tests**: `pytest` must pass (214+ tests, incl. pipeline, Modbus, panel).
5. **Hardware changes need hardware evidence**: if you touch Flash/Verify paths, note which board/OS you tested on.

## Architecture notes

- `firmforge/core/` — pipeline runner, board detector, resources (bundled data locator)
- `firmforge/providers/arduino/` — build (avr-gcc + ArduinoCore-avr) and flash (avrdude)
- `firmforge/adapters/` — CLI (`ff`), MCP server
- `firmforge/data/` — **bundled package data**: `boards/` (board.yaml), `knowledge/` (chip registers/pins), `vendor/` (toolchain download manifests)
- `firmforge/tools/` — serial panel HTML, Modbus utilities

### Path rules (important)

All bundled data lives under `firmforge/data/`. **Never** reference `./boards` or `./knowledge` directly — use `firmforge.core.resources` (`boards_dir()`, `knowledge_dir()`, ...). This keeps the package working from any cwd and from a pip install.

### Toolchains

avr-gcc / avrdude are downloaded at runtime by `ff setup` to `~/.firmforge/toolchains` (manifests in `firmforge/data/vendor/manifests/`). Never commit toolchain binaries.

## License

By contributing you agree that your contributions are licensed under the MIT License.
