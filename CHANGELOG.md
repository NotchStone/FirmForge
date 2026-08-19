# Changelog

All notable changes to FirmForge. Format: [Keep a Changelog](https://keepachangelog.com/), versions follow [SemVer](https://semver.org/).

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
