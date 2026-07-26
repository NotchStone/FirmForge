"""Toolchain detection and path resolution for Arduino AVR.

Search order:
  1. ~/.firmforge/toolchains/<tool>/   (FirmForge canonical install path)
  2. PATH                              (anywhere on system)
  3. ~/AppData/Local/mcu-tools/        (manual bare-metal install)
  4. winget                            (system package manager)

Strategy: canonical path checked first; fallback chain for backward
compatibility with existing toolchains from other install sources.
"""

from __future__ import annotations

import glob
import logging
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# Canonical toolchain root (planning §4.2)
CANONICAL_TOOLCHAIN_ROOT = Path.home() / ".firmforge" / "toolchains"


@dataclass
class ToolchainPaths:
    """Resolved toolchain executable paths."""
    avr_gcc: str
    avr_objcopy: str
    avrdude: str
    avrdude_conf: str | None = None
    bin_dir: str | None = None


def find_avr_gcc() -> tuple[str | None, str | None]:
    """Find avr-gcc executable. Returns (path, bin_dir).

    Search order: canonical → mcu-tools → winget → PATH.
    """
    # 0. Canonical path (FirmForge auto-install)
    canonical_bin = CANONICAL_TOOLCHAIN_ROOT / "avr-gcc" / "bin"
    gcc_exe = canonical_bin / "avr-gcc.exe"
    if gcc_exe.exists():
        return str(gcc_exe), str(canonical_bin)

    # 1. PATH
    try:
        r = subprocess.run(["avr-gcc", "--version"], capture_output=True,
                           text=True, timeout=5)
        if r.returncode == 0:
            return "avr-gcc", None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # 2. mcu-tools manual install
    home = os.path.expanduser("~")
    mcu_tools_gcc = os.path.join(
        home, "AppData", "Local", "mcu-tools", "avr-gcc", "bin", "avr-gcc.exe"
    )
    if os.path.exists(mcu_tools_gcc):
        return mcu_tools_gcc, os.path.dirname(mcu_tools_gcc)

    # 3. winget install
    pattern = os.path.join(
        home, "AppData", "Local", "Microsoft", "WinGet", "Packages",
        "ZakKemble.avr-gcc*"
    )
    dirs = glob.glob(pattern)
    if dirs:
        bin_dir = os.path.join(dirs[0], "bin")
        gcc_path = os.path.join(bin_dir, "avr-gcc.exe")
        if os.path.exists(gcc_path):
            return gcc_path, bin_dir

    return None, None


def find_avrdude() -> tuple[str | None, str | None]:
    """Find avrdude executable. Returns (path, conf_path).

    Search order: canonical → PATH → winget.
    """
    # 0. Canonical path
    canonical_avrdude = CANONICAL_TOOLCHAIN_ROOT / "avrdude"
    avrdude_exe = canonical_avrdude / "avrdude.exe"
    avrdude_conf = canonical_avrdude / "avrdude.conf"
    if avrdude_exe.exists():
        return str(avrdude_exe), str(avrdude_conf) if avrdude_conf.exists() else None

    # 1. PATH
    try:
        r = subprocess.run(["avrdude", "--version"], capture_output=True,
                           text=True, timeout=5)
        if r.returncode == 0:
            return "avrdude", None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # 2. winget install
    home = os.path.expanduser("~")
    pattern = os.path.join(
        home, "AppData", "Local", "Microsoft", "WinGet", "Packages",
        "AVRDudes.AVRDUDE*"
    )
    dirs = glob.glob(pattern)
    if dirs:
        exe_path = os.path.join(dirs[0], "avrdude.exe")
        conf_path = os.path.join(dirs[0], "avrdude.conf")
        if os.path.exists(exe_path):
            return exe_path, conf_path if os.path.exists(conf_path) else None

    return None, None


def resolve_toolchain() -> ToolchainPaths:
    """Resolve all Arduino AVR toolchain paths."""
    gcc_path, bin_dir = find_avr_gcc()
    avrdude_path, conf_path = find_avrdude()

    objcopy = "avr-objcopy"
    if bin_dir:
        objcopy = os.path.join(bin_dir, "avr-objcopy.exe")

    return ToolchainPaths(
        avr_gcc=gcc_path or "",
        avr_objcopy=objcopy,
        avrdude=avrdude_path or "",
        avrdude_conf=conf_path,
        bin_dir=bin_dir,
    )
