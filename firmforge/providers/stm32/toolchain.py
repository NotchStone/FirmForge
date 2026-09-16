"""STM32 工具链定位 —— arm-none-eabi-gcc + OpenOCD。

两者都是**例外 E3**（厂商安装器放好的外部工具，FirmForge 不下载不搬运），
声明在 `data/vendor/manifests/tools/{arm_gcc,openocd}.yaml`，本模块执行探测。

与 AVR 路线的差别（不是缺陷，是工具本身的性质）
------------------------------------------------

1. **ARM 工具链没有 winget 兜底**。AVR 走 `canonical → mcu-tools → winget → PATH`，
   ARM 只走 `canonical → manifest probe → PATH` —— 官方安装器把 700 MB 放进
   Program Files，重装一次代价高，所以 manifest 里写死了版本号那一段路径。

2. **OpenOCD 需要 scripts 目录**。`interface/*.cfg` 与 `target/*.cfg` 不在
   `bin/` 下。xPack 布局是 `<root>/openocd/scripts`，经典发行版是
   `<root>/share/openocd/scripts` —— manifest 用 `scripts_dir_candidates`
   把两种都列上，别在代码里写死。

探测失败时**不抛异常**，返回带空隙的 dataclass，由调用方（build/flash）给出
「装什么、装到哪」的可操作报错 —— 这比在导入期炸掉有用得多。
"""

from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from firmforge.infrastructure.tool_probe import (
    find_external_tool,
    resolve_relative,
)

logger = logging.getLogger(__name__)

#: arm-gcc 的四个必需可执行文件（相对 bin 目录）
_ARM_BINARIES = ("arm-none-eabi-gcc", "arm-none-eabi-g++",
                 "arm-none-eabi-objcopy", "arm-none-eabi-size")


@dataclass
class Stm32Toolchain:
    """解析后的 STM32 工具链路径。空字符串 = 未找到。"""

    gcc: str = ""
    gpp: str = ""
    objcopy: str = ""
    size: str = ""
    bin_dir: str | None = None

    openocd: str = ""
    openocd_scripts: str | None = None
    openocd_bin_dir: str | None = None

    #: 探测过程中的说明（成功来源 / 失败原因），供 `ff doctor` 展示
    notes: list[str] = field(default_factory=list)

    # -- 判定 ---------------------------------------------------------------

    @property
    def compiler_ready(self) -> bool:
        return bool(self.gcc and self.objcopy)

    @property
    def flasher_ready(self) -> bool:
        return bool(self.openocd and self.openocd_scripts)

    def problems(self) -> list[str]:
        """返回可操作的问题描述；空列表 = 全通。"""
        issues: list[str] = []
        if not self.compiler_ready:
            issues.append(
                "arm-none-eabi-gcc 未找到。装 ARM GNU Toolchain 14.2.Rel1 后，"
                "把 bin 目录加进 PATH，或改 "
                "firmforge/data/vendor/manifests/tools/arm_gcc.yaml 的 probe 路径。"
            )
        if not self.openocd:
            issues.append(
                "openocd 未找到。xPack 版 openocd 0.12.0 解包到 "
                "~/AppData/Local/mcu-tools/openocd/ 即可（探针走 bin/ 那一层）。"
            )
        elif not self.openocd_scripts:
            issues.append(
                f"openocd 找到了（{self.openocd}）但 scripts 目录没找到。"
                "需要 <root>/openocd/scripts 或 <root>/share/openocd/scripts。"
            )
        return issues

    def describe(self) -> dict[str, str]:
        return {
            "gcc": self.gcc or "(missing)",
            "openocd": self.openocd or "(missing)",
            "openocd_scripts": self.openocd_scripts or "(missing)",
        }


# --------------------------------------------------------------------------
# 探测
# --------------------------------------------------------------------------

def _probe_arm_binaries(bin_dir: str) -> dict[str, str]:
    """在 `bin_dir` 里凑齐四个必需可执行文件（缺的留空）。"""
    out: dict[str, str] = {}
    for name in _ARM_BINARIES:
        for candidate in (name, f"{name}.exe"):
            p = Path(bin_dir) / candidate
            if p.is_file():
                out[name] = str(p)
                break
    return out


def find_arm_gcc() -> tuple[str, str | None]:
    """找 arm-none-eabi-gcc。返回 (可执行文件, bin 目录)。"""
    # 1. canonical —— FirmForge 自管的安装位置（目前不用，但保持与 AVR 一致）
    from firmforge.infrastructure import paths
    canonical = paths.toolchains_dir() / "arm-none-eabi-gcc" / "bin"
    for candidate in ("arm-none-eabi-gcc", "arm-none-eabi-gcc.exe"):
        p = canonical / candidate
        if p.is_file():
            return str(p), str(canonical)

    # 2. manifest probe（Program Files 官方安装器 / mcu-tools）→ PATH
    tool = find_external_tool("arm_gcc", "arm-none-eabi-gcc")
    if tool:
        return tool.exe, tool.bin_dir
    return "", None


def find_openocd() -> tuple[str, str | None, str | None]:
    """找 openocd。返回 (可执行文件, bin 目录, scripts 目录)。"""
    from firmforge.infrastructure import paths
    canonical = paths.toolchains_dir() / "openocd" / "bin"
    for candidate in ("openocd", "openocd.exe"):
        p = canonical / candidate
        if p.is_file():
            scripts = _scripts_near(canonical)
            return str(p), str(canonical), scripts

    tool = find_external_tool("openocd", "openocd")
    if not tool:
        return "", None, None
    return tool.exe, tool.bin_dir, resolve_relative(tool, "scripts_dir_candidates")


def _scripts_near(bin_dir: Path) -> str | None:
    """canonical 安装下的 scripts 目录（两种布局都试）。"""
    for rel in ("../openocd/scripts", "../share/openocd/scripts"):
        p = (bin_dir / rel).resolve()
        if p.is_dir():
            return str(p)
    return None


# --------------------------------------------------------------------------
# 汇总
# --------------------------------------------------------------------------

def resolve_toolchain() -> Stm32Toolchain:
    """解析 STM32 路线全部工具路径。**不抛异常** —— 缺口由 problems() 报出。"""
    tc = Stm32Toolchain()

    gcc, bin_dir = find_arm_gcc()
    tc.gcc, tc.bin_dir = gcc, bin_dir
    if bin_dir:
        found = _probe_arm_binaries(bin_dir)
        tc.gpp = found.get("arm-none-eabi-g++", "")
        tc.objcopy = found.get("arm-none-eabi-objcopy", "")
        tc.size = found.get("arm-none-eabi-size", "")
        if gcc:
            tc.notes.append(f"arm-none-eabi-gcc ← {gcc}")
    elif gcc:
        # bare name resolved via PATH without a known bin_dir
        tc.gpp, tc.objcopy, tc.size = ("arm-none-eabi-g++",
                                       "arm-none-eabi-objcopy",
                                       "arm-none-eabi-size")
        tc.notes.append("arm-none-eabi-gcc ← PATH")

    oc, oc_bin, oc_scripts = find_openocd()
    tc.openocd, tc.openocd_bin_dir, tc.openocd_scripts = oc, oc_bin, oc_scripts
    if oc:
        tc.notes.append(f"openocd ← {oc}")
        if oc_scripts:
            tc.notes.append(f"openocd scripts ← {oc_scripts}")
        else:
            tc.notes.append("openocd scripts 目录未找到 —— 无法解析 interface/target cfg")

    for issue in tc.problems():
        logger.warning("STM32 toolchain: %s", issue)

    return tc


def version_of(exe: str, *args: str) -> str:
    """跑 `<exe> <args...> --version` 取首行；失败返回 'unknown'。"""
    if not exe:
        return "unknown"
    try:
        r = subprocess.run([exe, *args, "--version"], capture_output=True,
                           text=True, timeout=10)
        text = (r.stdout or r.stderr or "").strip()
        return text.splitlines()[0] if text else "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


__all__ = ["Stm32Toolchain", "resolve_toolchain", "find_arm_gcc",
           "find_openocd", "version_of"]
