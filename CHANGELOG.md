# Changelog

All notable changes to FirmForge. Format: [Keep a Changelog](https://keepachangelog.com/), versions follow [SemVer](https://semver.org/).

## [Unreleased]

### Added
- **`ff inspect <board>`** — read-only observation over SWD (STM32 only): decoded reset cause from `RCC_RSR` with the priority order of RM0433 Table 56 (IWDG1 timeout *also* sets PINRSTF, power-on sets PIN+BOR, so bit order is not priority order), PC → function/file/line, global symbols and arrays by name or glob, and peripheral registers with field-level decoding from the same knowledge base `ff context` uses. `--json` emits an `ff.inspect/1` document. It writes only three things, each switchable off and each reported in the output: halt/resume, the IWDG debug-freeze bit, and optionally `RCC_RSR` RMVF. The freeze bit is **verified by read-back** rather than assumed from OpenOCD's `stm32h7x.cfg`, and a snapshot is flagged untrustworthy when the watchdog is not frozen, when SP equals PC, or when SP falls outside every RAM region — all three were observed for real after clearing the freeze bit on a 10 ms-IWDG target (SP = `0x08004EE2`, exception IRQ210, **exit code still 0**). `--symbol-notes` maps variable values to human-readable stages from a YAML table, so the output can say "stage 7 = main loop running" without inspect understanding the firmware. Note: symbol lookup uses the ELF in `~/.firmforge/cache/build/…`, which is shared across projects, so the path and mtime are printed; use `--elf` to override.

### Changed
- **S5 Verify is now three-state**: `verified` (`--expected` matched) / `mismatch` / `collected` (data captured, no assertion supplied). Previously S5 could not fail — `success` was set unconditionally, including on internal errors. Zero bytes read back within 8 s now fails, and a non-matching `--expected` now fails. No serial port reports `SKIP` instead of `PASS`.
- **S5 has a distinct `port_busy` verdict**: a serial port that never opened (still held by the previous collector thread, or by another `ff` process) used to be reported as `empty` — "opened at 115200 bps but no bytes in the sampling window: firmware not running / wrong baud / TX not wired to RX" — which sends the investigation at the hardware. Missing precondition and empty result are now separate verdicts with separate remedies.
- **`--expected` must target periodic output** (heartbeat / status line), now stated in `--expected` help, the MCP schema, `board.yaml::serial`, and the `mismatch` error text. S5 opens the port only after flashing, so a one-shot boot banner is structurally unobservable; asserting on it produces a `mismatch` that looks like broken firmware. Firmware that wants to be verifiable should report version/state inside its heartbeat (`HEARTBEAT ver=1 tick=…`).
- **S5 gives up after 1.5 s when nothing arrives at all** (instead of the full 8 s window). Firmware that prints nothing will not produce a first line on the seventh second, so the long wait was pure latency on every silent-firmware diagnosis. The early exit keys on **bytes received**, not on lines parsed — firmware emitting a partial line without a newline still gets the full window.
- **`--json` works after the subcommand as well** (`ff build … --json`), not only in the global position (`ff --json build …`). The old behaviour made the intuitive form fail with `unrecognized arguments` on stderr and an empty stdout, which reads like "the command produced nothing".
- Serial I/O and port enumeration no longer depend on pySerial on Windows: port enumeration moved to Win32 SetupAPI (`providers/win32ports.py`), and `ComPort` fails fast instead of silently falling back (`FF_PYSERIAL_FALLBACK=1` restores the old behaviour).
- `board.yaml` for GC-H743 now carries the full pin map verified against the board schematic (pins, connectors CN1–CN19, peripheral alternate functions, and the naming traps: schematic CAN0 = FDCAN2, `USB_RX` is the MCU's TX, USB-A is CN3 not CN2).

### Fixed
- AVR flashing reported success whenever avrdude exited 0, including when it never opened the port (`Flash SUCCESS (0 bytes)`). Success now requires positive evidence — `N bytes of flash written` / `verified`, or a read-back verify pass.
- AVR flashing also treated a retried-handshake warning (`n sync`) as a hard failure, so successful writes were reported as failures.
- STM32 serial readback picked the first CH340 port when several were attached; it now refuses to guess (`serial.port` in `board.yaml` overrides detection).
- Serial fallback raised `Not a valid parity` and masked the real open error.
- Stage errors were truncated mid-traceback (`Error:  call last):`).
- S5 leaked its collector thread when the panel stayed resident, so the next run could not open the port; the previous collector is now stopped (and joined) before a new one starts.
- `ff run --panel-wait 0` printed a panel URL that was already dead: the in-process HTTP server dies with the CLI, so the address could never be opened ("the S5 panel is gone"). The URL is now withheld in that mode with an explicit note; it is still returned to MCP / `--json` callers, whose process stays alive. Use `--panel-wait <seconds>` for a panel you can actually look at.
- `--expected` no longer reuses a cached `flash=done`: a fingerprint match cannot prove the board is currently running that image, so an asserted run always really flashes (skipping it made S5 judge unknown firmware).
- Compiler output was decoded with the **system locale** (`subprocess.run(text=True)` → cp936 on Simplified-Chinese Windows) while `arm-none-eabi-gcc` emits UTF-8. Any diagnostic that echoed a source line containing a Chinese comment raised `UnicodeDecodeError` inside the reader thread, which left `r.stderr = None`; the caller's `stderr_all += r.stderr` then raised `TypeError` and S3 reported an *internal error* with no compiler error at all (`PYTHONUTF8=1` made it disappear — the fingerprint of a wrong-codec bug). Every provider now goes through `providers/textio.py::run_text()`: explicit `encoding="utf-8"`, `errors="replace"`, and `.stdout`/`.stderr` guaranteed to be `str`.

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
