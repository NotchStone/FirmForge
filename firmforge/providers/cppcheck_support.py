"""S2 静态分析的"编译上下文"—— 让 cppcheck 与编译器看到同一份世界。

**为什么需要这个模块（2026-10-27 实测）**

给 cppcheck 补上 `-I` 之后，它开始真正解析 CMSIS 头文件，于是立刻撞上
`cmsis_compiler.h:278  #error Unknown compiler.`：

```c
#if   defined ( __CC_ARM )
#elif defined ( __ARMCC_VERSION )
#elif defined ( __GNUC__ )
#else
  #error Unknown compiler.
#endif
```

cppcheck **不预定义** `__GNUC__`、`__arm__`、`__thumb__`、`__ARM_ARCH_7EM__`
这些编译器内建宏 —— 它们只存在于真实编译器里。缺了它们，任何"按编译器
分支"的头文件都会走到 `#else` 的 `#error`：

* 报出来的是一条 **error**（本该阻断构建），而错的是我们自己的调用方式；
* 更隐蔽的是 `#if` 分支取错值 —— 用户写的位号自检 `#error` 因此恒真。

**做法：问编译器自己要。** `gcc -dM -E` 打印它全部的内建宏（本机
arm-none-eabi-gcc 14.2 = 419 条），原样写成一份强制包含的头文件交给
cppcheck（`--include=`）。这样"cppcheck 眼里的编译器"与"真实的编译器"
是同一个东西，且不靠人工维护一张宏清单 —— 清单一定会落后于工具链升级。

为什么不逐个 `-D` 传：419 条宏 ≈ 15 KB 命令行，工程一多就会撞 Windows
32 KB 上限；`--include` 只占一个参数，且内容可缓存复用。
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from firmforge.providers.textio import run_text

logger = logging.getLogger(__name__)

#: `-dM` 里这些宏**不能**写进头文件：
#: 它们由预处理器在包含点求值，硬写成常量会让所有诊断的行号/文件名错位。
_SKIP_MACROS = frozenset({
    "__FILE__", "__LINE__", "__DATE__", "__TIME__", "__TIMESTAMP__",
    "__COUNTER__", "__BASE_FILE__", "__INCLUDE_LEVEL__",
    "__STDC_HOSTED__",
})


@dataclass
class CppcheckContext:
    """一次静态分析所需的编译侧事实。

    字段全部来自**真实编译配置**（board.yaml + 工具链），不是猜的：
    给 cppcheck 另一份 include / 宏，等于让它在另一个工程上分析。
    """

    include_dirs: list[str] = field(default_factory=list)
    defines: list[str] = field(default_factory=list)
    #: 强制包含的头文件（编译器内建宏的落地形态），见 `predefines_header()`
    force_includes: list[str] = field(default_factory=list)
    #: 厂家 SDK / 第三方库根目录。落在这些目录里的诊断照实报告但不阻断 ——
    #: 官方 HAL/CMSIS 过不过 cppcheck 与用户固件对不对无关。
    vendor_roots: list[str] = field(default_factory=list)
    #: 拿不到的部分写成可操作的说明，由 S2 原样打给用户
    problems: list[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.include_dirs or self.defines or self.force_includes)


def predefines_header(compiler: str | None, flags: Sequence[str] = (),
                      *, tag: str) -> tuple[str | None, str]:
    """把 `compiler -dM -E` 的内建宏写成一份可 `--include` 的头文件。

    Args:
        compiler: 编译器可执行文件路径（avr-gcc / arm-none-eabi-gcc）。
        flags: 影响内建宏的编译选项（`-mmcu=` / `-mcpu=` / `-mthumb` …）。
        tag: 缓存文件名前缀（如 `stm32h7` / `avr_atmega2560`）。

    Returns:
        `(头文件路径 or None, 说明)`。失败时第二项是可操作的原因，
        **不抛异常** —— S2 是"尽力给足上下文"，不是"缺一样就崩"。
    """
    if not compiler or not Path(compiler).is_file():
        return None, f"编译器不存在：{compiler}"

    from firmforge.infrastructure import paths
    key = _cache_key(compiler, flags)
    out_dir = paths.cache_dir() / "cppcheck" / "predefs"
    out = out_dir / f"{tag}_{key}.h"
    if out.is_file():
        return str(out), ""

    cmd = [compiler, "-dM", "-E", *flags, "-x", "c", os.devnull]
    try:
        r = run_text(cmd, timeout=60)
    except Exception as exc:                     # noqa: BLE001
        return None, f"取内建宏失败（{type(exc).__name__}: {exc}）"

    lines = (r.stdout or "").splitlines()
    if not lines:
        return None, "编译器未输出任何内建宏（-dM -E 返回空）"

    kept: list[str] = []
    for line in lines:
        m = re.match(r"#define\s+(\S+)", line)
        if not m or m.group(1) in _SKIP_MACROS:
            continue
        kept.append(line)

    header = (
        "/* 由 ff 自动生成 —— 不要编辑。\n"
        f" * 来源: {Path(compiler).name} -dM -E {' '.join(flags)}\n"
        " * 用途: 让 cppcheck 看到与真实编译器相同的内建宏（__GNUC__ / __arm__ …）。\n"
        " * 缺了它们，凡按编译器分支的头文件都会落到 #else 的 #error。\n"
        " */\n"
        + "\n".join(kept) + "\n")
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(".h.tmp")
        tmp.write_text(header, encoding="utf-8")
        tmp.replace(out)
    except OSError as exc:
        return None, f"写内建宏头失败：{exc}"
    logger.debug("cppcheck predefines: %s (%d 条宏)", out, len(kept))
    return str(out), ""


def _cache_key(compiler: str, flags: Sequence[str]) -> str:
    """编译器的路径 + 大小 + mtime + 影响宏的选项 → 短哈希。

    不用 `--version` 子进程：那要多起一次进程，而"哪个二进制"这件事
    路径+大小+mtime 已经足够区分（换工具链必然改这三样之一）。
    """
    h = hashlib.sha256()
    h.update(str(compiler).encode("utf-8"))
    try:
        st = Path(compiler).stat()
        h.update(f"{st.st_size}:{int(st.st_mtime)}".encode("utf-8"))
    except OSError:
        pass
    h.update("|".join(flags).encode("utf-8"))
    return h.hexdigest()[:16]


__all__ = ["CppcheckContext", "predefines_header"]
