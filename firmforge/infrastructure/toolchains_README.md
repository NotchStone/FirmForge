# FirmForge Toolchain Directory

All MCU toolchains managed by FirmForge are stored here.

## Canonical path: `~/.firmforge/toolchains/`

Following industry convention (PlatformIO `~/.platformio/`, Rust `~/.rustup/`,
ESP-IDF `~/.espressif/`), FirmForge uses its product name as the dot-directory prefix.

```
~/.firmforge/toolchains/
├── avr-gcc/              # avr-gcc + avr-libc (Arduino compilation)
│   └── bin/              # avr-gcc, avr-objcopy, avr-size
├── avrdude/              # avrdude + avrdude.conf (Arduino flashing)
│   └── avrdude.exe, avrdude.conf
├── arduino/              # Arduino.h + cores/arduino/ (Arduino API headers, libraries, examples)
│   └── cores/arduino/    # pinMode, digitalWrite, etc.
└── cppcheck/             # cppcheck static analysis (S2 Phase 1)
    └── bin/, scripts/

## Detection strategy (toolchain.py)

Provider searches: canonical path FIRST, then fallback chain:
  1. ~/.firmforge/toolchains/<tool>/   (canonical — FirmForge auto-install)
  2. PATH                              (user's system PATH)
  3. ~/AppData/Local/mcu-tools/        (legacy manual install)
  4. winget                            (system package manager)

FirmForge always installs NEW toolchains to canonical path.
Existing installs at legacy paths are detected but not moved.
