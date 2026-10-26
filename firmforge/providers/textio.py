"""子进程文本输出采集 —— 全 provider 共用。

**为什么需要这个模块（一次真实故障，2026-10-26）**

Windows 上 `subprocess.run(text=True)` 用 **系统区域编码** 解码子进程输出
（简体中文 Windows = cp936/gbk）。而 `arm-none-eabi-gcc` 输出的是 **UTF-8**：
只要诊断信息里回显了源码行、而源码里有中文注释，Python 的 reader 线程就会抛
`UnicodeDecodeError`，于是：

1. `r.stderr` 变成 `None`；
2. 调用方的 `stderr_all += r.stderr` 抛 `TypeError: can only concatenate str
   (not "NoneType") to str`；
3. 整个 S3 构建阶段以 "internal error" 收场，**编译器其实一行错都没有**。

当时的现场是：把中文注释写进 `.c` 文件后，`ff build` 直接崩在 pipeline 里，
而 `PYTHONUTF8=1` 一加就好 —— 这正是"解码用错编码"的典型指纹。

**修法只有一条正路**：显式 `encoding="utf-8", errors="replace"`。
`errors="replace"` 保证"某个工具吐了一个非法字节"永远只损失那个字符，
不会升级成"构建崩溃"。任何一处漏掉，这个故障就会在"某个源文件第一次写了
非 ASCII 字符"的那天复现 —— 所以统一走这里，不要在各处手写 subprocess 参数。
"""

from __future__ import annotations

import subprocess
from typing import Sequence


def run_text(cmd: Sequence[str], *,
             timeout: float | None = None,
             **kwargs) -> subprocess.CompletedProcess:
    """运行命令并采集输出，**按 UTF-8 解码**。

    与 `subprocess.run(..., capture_output=True, text=True)` 的区别：
      · `text=True` 用区域编码解码 → 本函数用 UTF-8；
      · `errors="replace"` → 非法字节替换为 U+FFFD，不让解码失败冒泡；
      · 返回值的 `.stdout` / `.stderr` **保证是 str**（不会是 None），
        调用方不必写 `or ""`。

    其余关键字参数（`cwd` / `env` / `input` / `check` ...）原样透传。
    """
    for key in ("text", "encoding", "errors", "capture_output"):
        kwargs.pop(key, None)

    r = subprocess.run(list(cmd), capture_output=True, text=True,
                       encoding="utf-8", errors="replace",
                       timeout=timeout, **kwargs)

    # 正常情况下 subprocess 已经给了 str；这里兜一手：一旦某个平台/版本
    # 因为 reader 线程异常留下 None，也不把 TypeError 传给调用方。
    if r.stdout is None:
        r.stdout = ""
    if r.stderr is None:
        r.stderr = ""
    return r


__all__ = ["run_text"]
