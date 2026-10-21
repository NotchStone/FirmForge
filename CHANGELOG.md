# Changelog

All notable changes to FirmForge. Format: [Keep a Changelog](https://keepachangelog.com/), versions follow [SemVer](https://semver.org/).

## [Unreleased]

### Changed
- **S5 Verify is now three-state**: `verified` (`--expected` matched) / `mismatch` / `collected` (data captured, no assertion supplied). Previously S5 could not fail — `success` was set unconditionally, including on internal errors. Zero bytes read back within 8 s now fails, and a non-matching `--expected` now fails. No serial port reports `SKIP` instead of `PASS`.
- Serial I/O and port enumeration no longer depend on pySerial on Windows: port enumeration moved to Win32 SetupAPI (`providers/win32ports.py`), and `ComPort` fails fast instead of silently falling back (`FF_PYSERIAL_FALLBACK=1` restores the old behaviour).

### Fixed
- AVR flashing reported success whenever avrdude exited 0, including when it never opened the port (`Flash SUCCESS (0 bytes)`). Success now requires positive evidence — `N bytes of flash written` / `verified`, or a read-back verify pass.
- AVR flashing also treated a retried-handshake warning (`n sync`) as a hard failure, so successful writes were reported as failures.
- STM32 serial readback picked the first CH340 port when several were attached; it now refuses to guess (`serial.port` in `board.yaml` overrides detection).
- Serial fallback raised `Not a valid parity` and masked the real open error.
- Stage errors were truncated mid-traceback (`Error:  call last):`).

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
