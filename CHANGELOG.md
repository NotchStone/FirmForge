# Changelog

All notable changes to FirmForge. Format: [Keep a Changelog](https://keepachangelog.com/), versions follow [SemVer](https://semver.org/).

## [0.3.0] - 2026-08-20

### Added
- `ff --json` — machine-readable JSON output for all commands (detect/run/build/flash/context); pure-JSON stdout for agent/plugin integration
- `ff context [board] [--topic]` — chip knowledge reference (registers/pins/baud) as a CLI command
- `tests/test_cli_json.py` — 7 tests asserting JSON parseability and structure

### Fixed
- `ff_context` pins were always empty for `arduino_328p` (pins.json board label `arduino_uno` mismatch) — chip-alias lookup in knowledge base
- `ff_context` with an unknown board silently returned ATmega328P data — now returns an explicit error (prevents agent hallucination on wrong chip data)
- CLI `--version` reported 0.1.0 (out of sync with pyproject)

## [0.2.0] - 2026-08-19

### Added
- `ff setup` — cross-platform toolchain installer (avr-gcc 14.1.0, avrdude, cppcheck, Arduino Core) with idempotent re-runs; avrdude extracted from the avr-gcc bundle
- GitHub Actions CI: pytest on push/PR; wheel build + attach to Release on tag
- Bundled package data (`firmforge/data/`): boards, chip knowledge, toolchain manifests — works from any cwd and from pip installs
- `firmforge.core.resources` — cwd-independent locator for bundled data

### Changed
- Data layout: `boards/`, `knowledge/`, `vendor/` moved into `firmforge/data/`
- Toolchain manifests updated to ZakKemble GitHub releases (Arduino official download URLs had gone 404)
- Missing toolchain now reports a friendly "run `ff setup`" message instead of a raw error

### Fixed
- Serial panel: FC06 Count label hiding, FC06/16 echo decoding, Data input layout, 0x-hex input support, space/Chinese-comma separators for FC16
- Recovered Mega example apps (19 files) lost during data-layout migration

## [0.1.0] - 2026-07

- Initial MVP: 5-stage pipeline (Detect → Review → Build → Flash → Verify) for AVR (ATmega2560/328P)
- Serial panel + Modbus RTU master (FC03/04/06/16), MCP server, `ff` CLI
