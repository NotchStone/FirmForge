# Changelog

All notable changes to FirmForge. Format: [Keep a Changelog](https://keepachangelog.com/), versions follow [SemVer](https://semver.org/).

## [Unreleased]

### Added
- **`ff detect` now identifies STM32 boards over SWD** (CMSIS-DAP / ST-Link), instead of relying on COM-port VID/PID. A CMSIS-DAP adapter is an **HID device with no COM port**, so the port scan could never see it — adding `0D28:0204` to the VID/PID table would have been dead code, and an adapter being present would still say nothing about which board sits behind it. The new probe reads `DBGMCU_IDCODE` (`0x5C001000`, confirmed against `stm32h743xx.h` and measured as `0x20036450` on the test board) through OpenOCD and matches `DEV_ID` against `board.yaml::mcu.dev_id`. Confidence is 0.85 rather than AVR's 0.95 because `DEV_ID` only resolves to a **series** — H742/H743/H753/H750 all report `0x450` — so identifying a board also depends on exactly one registered board declaring that ID; if two ever share it, both are returned and `board_id` stays empty rather than guessing. The probe runs only when the AVR probe and USB scan found nothing (an AVR run must not start OpenOCD), it restores the CPU to running afterwards, and it separates "probe present but target offline" from "no probe" in `DetectionResult.notes` — the two call for different remedies.
- **`ff inspect <board>`** — read-only observation over SWD (STM32 only): decoded reset cause from `RCC_RSR` with the priority order of RM0433 Table 56 (IWDG1 timeout *also* sets PINRSTF, power-on sets PIN+BOR, so bit order is not priority order), PC → function/file/line, global symbols and arrays by name or glob, and peripheral registers with field-level decoding from the same knowledge base `ff context` uses. `--json` emits an `ff.inspect/1` document. It writes only three things, each switchable off and each reported in the output: halt/resume, the IWDG debug-freeze bit, and optionally `RCC_RSR` RMVF. The freeze bit is **verified by read-back** rather than assumed from OpenOCD's `stm32h7x.cfg`, and a snapshot is flagged untrustworthy when the watchdog is not frozen, when SP equals PC, or when SP falls outside every RAM region — all three were observed for real after clearing the freeze bit on a 10 ms-IWDG target (SP = `0x08004EE2`, exception IRQ210, **exit code still 0**). `--symbol-notes` maps variable values to human-readable stages from a YAML table, so the output can say "stage 7 = main loop running" without inspect understanding the firmware. Note: symbol lookup uses the ELF in `~/.firmforge/cache/build/…`, which is shared across projects, so the path and mtime are printed; use `--elf` to override.

- **Register review now separates "not in the knowledge base" from "hallucinated"**, using the CMSIS device header as a second, independent judge (`knowledge/device_truth.py`). The knowledge base is generated from SVDs, and ~100 H7 registers are absent from its SVD (`TIM2.RCR` among them); a hallucinated register (`GPIOA.BOGUS`) is absent too. Both were previously reported with the *same* message — `Peripheral register 'X.Y' not found in reference library` — so the tool stated "you are wrong" while it only meant "I don't know". Now: present in the header → `warning` tagged `kb-gap` with the header as evidence (`TIM_TypeDef.RCR`); absent from the header as well → `error`; header unavailable, or the instance is not in either header (`DMA1_Stream0`'s macro family) → `warning`, no verdict. The header is parsed from `packages/stm32/.../stm32h743xx.h` (242 instances / 77 structs) **and** from `CMSIS/Core/Include/core_cm7.h`, because the core blocks (SCB / DWT / SysTick / CoreDebug / NVIC) exist only in the latter — otherwise a typo inside a core block could never be more than a warning. `SourceReviewResult.kb_gaps` counts these separately, and they are excluded from the confidence denominator: the tool did not judge them, so it must not charge the source for them.
- **`.ff-review.yaml` — project-level review exemptions, with a mandatory reason.** `cppcheck-suppress` comments only affect cppcheck; the register review never read them, so a project had no way to say "these three are CMSIS core blocks, I checked them" short of turning review off. Entries take `symbol` / optional `file` / required `reason`; a missing reason makes the entry **inert** and reports why. Exempted items still print, tagged `[allowed: <reason>]`, and are removed from the confidence denominator — exemption means "not charged", never "invisible". Matching is exact on the symbol (no prefixes or wildcards), so one table cannot silently absorb names that appear later.
- **`ff inspect --app` / `--pc`** — see above; `--app` was added together with a refusal to guess between multiple cached ELFs.
- `ConfidenceReport.category_scores` — per-category scores (`registers` / `fields` / `pins` / `baud_rate`), each with `checked` / `resolved` / `score`. `ConfidenceCheck` no longer carries per-register 100%-entries, which double-counted the same reference in both `registers` and `pins`.

### Changed
- **Confidence no longer has a hard cap.** Any source-review error used to force `min(30, avg)` — one misspelled register made the whole project read as 30%, a number that cannot be explained and cannot direct any action. Adding `cap_reason` to explain "why 30" was writing documentation for a broken design, so both are gone. Penalty now lands only on the category that failed: 10 registers with 2 wrong scores `registers 80%` instead of 30%, and `needs_review` trips when the total **or any single category** falls below the threshold. Knowledge-base gaps and exempted items are subtracted from the denominator, so `TIM2->RCR` costs nothing.
- **`Source review:` needs a location to be actionable.** The summary line used to read `FAIL (registers 7/9)` — enough to know two failed, not enough to know which two or where, so the reader had to re-run the review per file to find out. It now carries the first three `file:line symbol` hits, and the denominator excludes what was never judged （`registers 0/0，2 条未收录不判定`）。
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
