"""GCC 诊断解析 —— 编译器 stderr → 结构化 `BuildDiagnostic`。

**为什么是共用模块而不是每个平台一份**：avr-gcc / arm-none-eabi-gcc / gcc 的
诊断格式是同一套（`file:line:col: error: msg`），差别只在名字。两份实现会在
第二次修 bug 时开始分叉 —— 统一放在 providers 层，因为它描述的是"编译器输出"
这个平台无关的东西，与具体工具链无关。

这是 COMPILE_FIX 的第一步输出，直接进 LLM 上下文，所以 `raw` 保留原文。
"""

from __future__ import annotations

import re

from firmforge.providers.base import BuildDiagnostic

__all__ = ["parse_gcc_diagnostics"]

#: `file:line:col: error: message`（也匹配 warning/note/fatal error）
_DIAG_RE = re.compile(
    r'^(.+?):(\d+):(\d+):\s*(error|warning|fatal error|note):\s*(.+)$',
    re.MULTILINE,
)


def parse_gcc_diagnostics(stderr: str) -> list[BuildDiagnostic]:
    """把 GCC 风格 stderr 解析成诊断列表。

    覆盖三类：
      1. `file:line:col: severity: message` —— 常规错误/警告
      2. `undefined reference to 'sym'` —— 链接期符号缺失（**只有「名字」，
         没有独立行号**，是最难归因的一类，必须单独拎出来）
      3. `ld returned ... exit status` / `collect2` —— 链接器整体失败，
         原文太少不足以定位，抓前后 3 行上下文当 `raw`
    """
    diagnostics: list[BuildDiagnostic] = []

    for match in _DIAG_RE.finditer(stderr):
        severity = match.group(4)
        if severity == "fatal error":
            severity = "error"
        elif severity == "note":
            continue          # note 是附注，不是独立问题
        diagnostics.append(BuildDiagnostic(
            severity=severity,
            file=match.group(1).strip(),
            line=int(match.group(2)),
            column=int(match.group(3)),
            message=match.group(5).strip(),
            raw=match.group(0).strip(),
        ))

    if "undefined reference" in stderr:
        for line in stderr.splitlines():
            if "undefined reference" in line:
                diagnostics.append(BuildDiagnostic(
                    severity="error",
                    message=line.strip(),
                    raw=line.strip(),
                ))

    if "ld returned" in stderr or "collect2" in stderr:
        lines = stderr.splitlines()
        for i, line in enumerate(lines):
            if "ld returned" in line or "collect2" in line:
                context = "\n".join(lines[max(0, i - 3):i + 3])
                diagnostics.append(BuildDiagnostic(
                    severity="error",
                    message=line.strip(),
                    raw=context.strip(),
                ))

    return diagnostics
