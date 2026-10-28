"""项目级审查豁免表 —— 「这几处我核对过，别算了」。

为什么不在代码里写 ``// cppcheck-suppress``
--------------------------------------------
cppcheck 的抑制注释只对 cppcheck 生效，寄存器审查（S2 的 review 子阶段）是
本工具自己的扫描，**根本不读那些注释**。于是项目里出现「某处已知无害、但每次
都报」的情况时，用户没有任何表达渠道 —— 要么忍着看噪声，要么关掉整个审查。
两种结果都是把工具变成噪声源。

本条要解决的就是这个：**允许项目显式声明豁免，但必须带理由**。

格式（放应用目录或工作区根，文件名 ``.ff-review.yaml``）::

    allow:
      - symbol: "SCB.CFSR"
        reason: "CMSIS 内核块，已对照 core_cm7.h 第 1234 行"
      - symbol: "IWDG1.PR"
        file: bsp_init.c            # 可选；只在这一份文件里豁免
        reason: "知识库按 SVD 命名收录为 IWDG，同名外设"

三条纪律
--------
1. **理由必填。** 空理由 = 无效条目，直接报警，不静默生效。豁免是承诺，
   不带理由的承诺等于「别管我」，那不是工程判断。
2. **仍然原样打印。** 命中豁免的条目从 ``violations`` 移到 ``allowed``，
   但输出里照列，标注 ``[allowed: <理由>]``。豁免的意义是「不计惩罚」，
   不是「看不见」。
3. **只按符号匹配，不做前缀/通配。** 通配会让一张表悄悄覆盖一批新出现的
   名字，而豁免恰恰是「这一处」而非「这一类」。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: 约定文件名。放应用目录或工作区根都认。
ALLOWLIST_FILENAME = ".ff-review.yaml"

#: 向上查找的最大层数 —— 防止从深层源码目录一路爬到盘根。
MAX_UPWARD_LEVELS = 4


@dataclass(frozen=True)
class AllowRule:
    """一条豁免声明。"""

    symbol: str
    reason: str
    #: 限定到某份文件（相对路径尾部匹配）。空串 = 该符号全局豁免。
    file: str = ""
    #: 出现在哪个 allowlist 文件里（诊断用）。
    origin: str = ""

    def as_dict(self) -> dict[str, str]:
        return {"symbol": self.symbol, "reason": self.reason,
                "file": self.file, "origin": self.origin}


@dataclass
class ReviewAllowlist:
    """已加载的豁免表。空表 = 什么都不豁免。"""

    rules: list[AllowRule] = field(default_factory=list)
    #: 生效的 allowlist 文件路径（没有则为空串）
    origin: str = ""
    #: 无效条目与加载问题 —— 必须打出来，不能静默
    problems: list[str] = field(default_factory=list)

    # -- 查询 ------------------------------------------------------------

    def __bool__(self) -> bool:
        return bool(self.rules)

    def __len__(self) -> int:
        return len(self.rules)

    def match(self, symbol: str, file: str = "") -> AllowRule | None:
        """按符号（和可选文件）找豁免规则。

        Args:
            symbol: ``外设.寄存器`` 或裸符号名，大小写不敏感。
            file: 违规所在文件（绝对或相对路径均可）。

        Returns:
            命中的规则，没有则 None。
        """
        want = symbol.upper()
        for rule in self.rules:
            if rule.symbol.upper() != want:
                continue
            if rule.file and not _file_matches(file, rule.file):
                continue
            return rule
        return None

    # -- 装载 ------------------------------------------------------------

    @classmethod
    def load(cls, start: Path | str | None) -> "ReviewAllowlist":
        """从 ``start`` 起向上查找 ``.ff-review.yaml``。

        找不到就返回空表（**不是错误**：绝大多数项目不需要豁免表）。
        """
        if start is None:
            return cls()
        path = find_allowlist_file(start)
        if path is None:
            return cls()
        return cls.from_file(path)

    @classmethod
    def from_file(cls, path: Path | str) -> "ReviewAllowlist":
        """读一个 allowlist 文件。解析失败不抛异常，只记问题。"""
        path = Path(path)
        table = cls(origin=str(path))
        try:
            import yaml
        except ImportError:
            table.problems.append(
                "读不到 PyYAML，豁免表未生效 —— 这不是配置错误，是环境缺依赖")
            return table

        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, UnicodeDecodeError) as e:
            table.problems.append(f"{path.name} 读取失败：{e}")
            return table
        except Exception as e:              # noqa: BLE001 —— yaml 语法错
            table.problems.append(f"{path.name} 不是合法 YAML：{e}")
            return table

        if not isinstance(raw, dict):
            table.problems.append(f"{path.name} 顶层应是映射（allow: [...]），"
                                  f"实际是 {type(raw).__name__}")
            return table

        entries = raw.get("allow")
        if entries is None:
            table.problems.append(f"{path.name} 里没有 allow: 段，文件被忽略")
            return table
        if not isinstance(entries, list):
            table.problems.append(f"{path.name} 的 allow: 应是列表")
            return table

        for idx, entry in enumerate(entries, start=1):
            rule = _parse_entry(entry, idx, table)
            if rule is not None:
                table.rules.append(rule)
        return table


# ---------------------------------------------------------------------------
# 内部
# ---------------------------------------------------------------------------


def find_allowlist_file(start: Path | str) -> Path | None:
    """从 start 起向上最多找 MAX_UPWARD_LEVELS 层同名文件。"""
    p = Path(start)
    if p.is_file():
        p = p.parent
    try:
        p = p.resolve()
    except OSError:
        pass
    for _ in range(MAX_UPWARD_LEVELS):
        candidate = p / ALLOWLIST_FILENAME
        if candidate.is_file():
            return candidate
        if p.parent == p:
            break
        p = p.parent
    return None


def _parse_entry(entry: Any, idx: int, table: ReviewAllowlist) -> AllowRule | None:
    """校验单条豁免；无效条目记进 problems 并返回 None。"""
    if not isinstance(entry, dict):
        table.problems.append(f"第 {idx} 条不是映射，已跳过")
        return None
    symbol = str(entry.get("symbol") or "").strip()
    reason = str(entry.get("reason") or "").strip()
    file = str(entry.get("file") or "").strip()
    if not symbol:
        table.problems.append(f"第 {idx} 条缺 symbol，已跳过")
        return None
    if not reason:
        # 理由必填 —— 这一条是整张表的立身之本
        table.problems.append(
            f"第 {idx} 条（{symbol}）没写 reason，**未生效** —— "
            f"豁免必须说明为什么安全，否则等同于关掉审查")
        return None
    return AllowRule(symbol=symbol, reason=reason, file=file,
                     origin=table.origin)


def _file_matches(actual: str, wanted: str) -> bool:
    """文件匹配：按路径尾部比较，容忍分隔符与大小写差异。

    ``wanted=bsp_init.c`` 命中 ``C:/proj/app/bsp_init.c``；
    ``wanted=app/bsp_init.c`` 也命中。不做模糊匹配 —— 目录层级写错就该不命中。
    """
    if not actual:
        return False
    a = actual.replace("\\", "/").lstrip("./").lower()
    w = wanted.replace("\\", "/").lstrip("./").lower()
    return a == w or a.endswith("/" + w)


def summarize(table: ReviewAllowlist) -> str:
    """一行摘要（进 S2 日志）。"""
    if not table.rules:
        return ""
    files = sorted({r.file for r in table.rules if r.file})
    scope = f"（{len(files)} 条限定到具体文件）" if files else "（全局）"
    return f"审查豁免 {len(table.rules)} 条{scope}，来自 {table.origin}"
