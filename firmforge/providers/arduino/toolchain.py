"""Toolchain detection and path resolution for Arduino AVR.

位置声明在 `data/vendor/manifests/tools/{avr_gcc,avrdude}.yaml`（与 STM32 侧
`tool_probe` 同一机制），本模块只做汇总。改探测位置改 manifest，不改代码。

Search order (manifest probe → probe_glob → PATH):
  1. ~/.firmforge/toolchains/<tool>/bin/   (ff setup 的 canonical 安装)
  2. mcu-tools / winget 等手动安装位置     (manifest 的 probe / probe_glob)
  3. PATH

注：avrdude 的 canonical 布局是 `toolchains/avrdude/bin/avrdude.exe` ——
setup.py 从 avr-gcc bundle 抽出后复制到 `root/bin/`。旧代码查的是扁平
`toolchains/avrdude/avrdude.exe`，从未命中过（一直靠 PATH 兜底工作）；
manifest 里两个布局都列了，bin/ 优先。
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from firmforge.infrastructure.tool_probe import find_external_tool

logger = logging.getLogger(__name__)


@dataclass
class ToolchainPaths:
    """Resolved toolchain executable paths."""
    avr_gcc: str
    avr_objcopy: str
    avrdude: str
    avrdude_conf: str | None = None
    bin_dir: str | None = None


def find_avr_gcc() -> tuple[str | None, str | None]:
    """Find avr-gcc executable. Returns (path, bin_dir)."""
    tool = find_external_tool("avr_gcc", "avr-gcc")
    if not tool:
        return None, None
    return tool.exe, tool.bin_dir


def find_avrdude() -> tuple[str | None, str | None]:
    """Find avrdude executable. Returns (path, conf_path)."""
    tool = find_external_tool("avrdude", "avrdude")
    if not tool:
        return None, None
    # conf 与可执行文件同目录：canonical（bin/）与 winget（包根）都如此。
    return tool.exe, tool.resolve("avrdude.conf")


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
