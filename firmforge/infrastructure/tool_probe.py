"""外部工具探测 —— 读 `vendor/manifests/tools/*.yaml`，按声明的 probe 路径定位。

例外 E3（`docs/路径分区标准.md` §3.1）：`arm-none-eabi-gcc` / `openocd` 由厂商
安装器放在 Program Files / AppData，FirmForge **不下载不搬运**，只声明 + 探测。
本模块是那条声明的执行端 —— manifest 是数据，这里是把数据变成路径的那几行。

probe 条目语义（**重要，别再猜**）
---------------------------------
每个条目是**直接包含目标可执行文件的那一层目录**。xPack 版 OpenOCD 的安装根
下有一个与可执行文件同名的子目录（`openocd/openocd/`），所以只写安装根会被
误判成命中 —— 见 `_bin_exists` 的注释。写 manifest 时一律写到 `bin` 那一层。
"""

from __future__ import annotations

import glob
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from firmforge.core.resources import manifests_dir

__all__ = ["ExternalTool", "bin_exists", "find_external_tool",
           "manifest_path", "load_manifest", "resolve_relative"]


def manifest_path(tool: str) -> Path:
    """`vendor/manifests/tools/<tool>.yaml`。"""
    return manifests_dir() / "tools" / f"{tool}.yaml"


def load_manifest(tool: str) -> dict:
    """读工具 manifest；不存在时返回空 dict（调用方据此给可操作的报错）。"""
    path = manifest_path(tool)
    if not path.is_file():
        return {}
    import yaml
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def bin_exists(root: Path | str, bin_rel: str) -> bool:
    """`bin_rel`（或 Windows 下的 `bin_rel.exe`）是否为 `root` 下的**文件**。

    必须用 `is_file()` 而非 `exists()` —— 目录会被 `exists()` 判真。
    """
    root = Path(root)
    p = root / bin_rel
    if p.is_file():
        return True
    if os.name == "nt" and not bin_rel.lower().endswith(".exe"):
        return (root / (bin_rel + ".exe")).is_file()
    return False


@dataclass(frozen=True)
class ExternalTool:
    """探测到的外部工具。`exe` 是完整路径，或裸名（命中 PATH 时）。"""

    tool: str
    exe: str
    bin_dir: str | None
    install: dict
    on_path: bool = False

    def resolve(self, relative: str) -> str | None:
        """把相对 `bin_dir` 的路径解析成绝对路径，不存在返回 None。"""
        if not self.bin_dir:
            return None
        p = (Path(self.bin_dir) / relative).resolve()
        return str(p) if p.exists() else None


def _found_at(bin_dir: Path, name: str, tool: str,
              install: dict) -> ExternalTool | None:
    """`name`（或其 .exe）是 `bin_dir` 下的文件 → 命中，否则 None。"""
    if not (bin_dir.is_dir() and bin_exists(bin_dir, name)):
        return None
    # Prefer the real filename (`.exe` on Windows) over the bare name.
    candidate = bin_dir / name
    if not candidate.is_file():
        candidate = bin_dir / f"{name}.exe"
    return ExternalTool(tool=tool, exe=str(candidate),
                        bin_dir=str(bin_dir), install=install)


def find_external_tool(tool: str, binary: str | None = None) -> ExternalTool | None:
    """定位 `tool`，返回 `ExternalTool` 或 None。

    顺序：manifest 的 `probe` 精确路径 → `probe_glob` 通配路径 → PATH。
    `binary` 缺省取 manifest 的 `install.binaries[0]`。找不到时返回 None
    （**不抛异常**），由调用方决定是降级还是给可操作的报错。

    `probe_glob` 用于 winget 这类**目录名带版本号**的安装位置
    （如 `ZakKemble.avr-gcc_*`）—— 精确路径写不了，只能通配。
    """
    manifest = load_manifest(tool)
    install = manifest.get("install", {}) or {}
    names = install.get("binaries", []) or []
    name = binary or (names[0] if names else tool)

    for raw in install.get("probe", []) or []:
        hit = _found_at(Path(os.path.expanduser(str(raw))), name, tool, install)
        if hit:
            return hit

    for raw in install.get("probe_glob", []) or []:
        for candidate_dir in sorted(glob.glob(os.path.expanduser(str(raw)))):
            hit = _found_at(Path(candidate_dir), name, tool, install)
            if hit:
                return hit

    found = shutil.which(name)
    if found:
        return ExternalTool(tool=tool, exe=found,
                            bin_dir=str(Path(found).parent),
                            install=install, on_path=True)
    return None


def resolve_relative(tool_obj: ExternalTool, key: str) -> str | None:
    """按 manifest 里 `key` 声明的候选相对路径（相对 `bin_dir`）找目录。

    用于 OpenOCD 的 `scripts_dir_candidates`：xPack 装在 `<root>/openocd/scripts`，
    经典发行版装在 `<root>/share/openocd/scripts`，同一份 manifest 要都能命中。
    """
    for rel in tool_obj.install.get(key, []) or []:
        hit = tool_obj.resolve(str(rel))
        if hit and Path(hit).is_dir():
            return hit
    return None
