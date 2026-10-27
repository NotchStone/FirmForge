"""Cppcheck 静态分析集成（S2 Phase 1）。

**铁律：工具说了什么就返回什么，不用聚合数字替代明细。**

2026-10-27 修的一批问题，全部来自同一个根因 —— 解析层把 cppcheck 的输出
吃掉了，上层拿到的只是"看起来像结论的数字"：

1. **路径冒号错位（闸门直接失效）**
   旧代码用 `line.split(":", 3)` 解析 `{file}:{line}:{severity}:{message}`。
   Windows 路径带盘符冒号，`C:\\...\\blackbox.c:161:error:...` 被切成
   `['C', '\\...\\blackbox.c', '161', 'error:...']` —— `severity` 变成
   `'161'`，`severity == "error"` 永远不成立，于是 **任何 cppcheck error
   都不阻塞构建**。实测：故意写一个 `#error`，日志仍报 0 errors。
   现在模板改成 **制表符分隔且带 `{id}`**（`{id}` 是规则名，如
   `uninitializedVariable`），文件路径里的冒号再也参与不了切分。

2. **`--suppress` 的 id 拼错**
   `constParameter` 在 2.21 里已经被拆成 `constParameterPointer` /
   `constParameterReference`；`stm32h7xx_hal.h` 是**引号包含**，真实 id 是
   `missingInclude` 而不是 `missingIncludeSystem`。拼错的抑制项既压不住噪声，
   还会额外产生一条 `unmatchedSuppression`。现在：
     · 抑制项只保留 **在 2.21 的 `--errorlist` 里确认存在、且确实会触发** 的；
     · `unmatchedSuppression` 不再被当 `information` 丢掉，而是进 `meta`
       并且**在 notes 里点名** —— 抑制项写错这件事必须自己暴露出来，
       否则下次还是同一种坑，只不过换了个 id。

3. **头文件当独立编译单元**
   `.h` 直接喂给 cppcheck 会在"没有包含者上下文"的情况下被分析：跨 TU 的
   ABI 结构体成员必然全报 `unusedStructMember`（实测 115 条里 86 条是它），
   而且没有任何 `-D`，`#if` 分支判定失真 —— 用户的位号自检 `#error`
   因此恒真。头文件不是翻译单元，现在不再单独分析，改为通过包含它的
   `.c/.cpp/.ino` 一起分析，并把这件事写进 notes。

4. **不给 `-I` / `-D`**
   `missingInclude: stm32h7xx_hal.h not found` 会让 cppcheck 对该 TU 的分析
   全部失真（宏未定义 → `#if` 分支取错）。现在由各平台提供者提供
   `cppcheck_context()`，把**编译用的同一份** include 路径与宏传进来。
   拿不到时**不假装分析过**：notes 里明确写"未提供 include 路径，结果带水分"。

5. **失败被吞成"0 errors"**
   超时 / 调用异常原先 `return []` —— 上层于是看到"没问题"。现在一律
   `ok=False` + `status` + 原始输出，把"没跑成"与"跑了且干净"分开。

6. **`--json` 里没有原始输出**
   机器调用方只能 import 内部 API 才能拿到明细。现在 `raw` 原样保留
   （stdout+stderr 全文），进 `details["cppcheck_raw"]`。
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

from firmforge.providers.textio import run_text

logger = logging.getLogger(__name__)

#: 模板字段顺序即切分顺序。**必须制表符分隔**：Windows 路径里必然有 `:`。
#: `{id}` 是规则名（`uninitvar` / `preprocessorErrorDirective` …），
#: 分桶统计和抑制项自检都靠它。
_TEMPLATE = "{file}\t{line}\t{column}\t{severity}\t{id}\t{message}"

#: 会阻塞构建的 severity。cppcheck 的 error 全是"确定有问题"级别。
BLOCKING_SEVERITIES = ("error",)

#: 默认抑制项 —— 每一条都要能在 `cppcheck --errorlist` 里查到，且确实会触发。
#: 拼错的抑制项会以 `unmatchedSuppression` 出现在 meta 里（见 `_classify`）。
DEFAULT_SUPPRESS = (
    # 标准库头不提供给 cppcheck 是官方推荐用法（它内置了声明）。
    # 只影响 `<stdio.h>` 这类尖括号包含，不影响项目自己的头文件。
    "missingIncludeSystem",
    # 中断服务函数字面上没人调用；嵌入式里的 ISR / 向量表入口全属此类。
    "unusedFunction",
    # 2.21 已把 constParameter 拆成三个（Pointer / Reference / Callback），
    # 实测会命中的是前两个。留着旧名只会白送 unmatchedSuppression。
    "constParameterPointer",
    "constParameterReference",
)

#: 默认超时。旧值 30 s 在真实工程上会超时（实测 H743 工程单次约 40 s），
#: 而超时被吞成"0 issues"比慢更糟。需要更快就靠缓存，不靠砍超时。
DEFAULT_TIMEOUT_S = 180.0

#: 分析源文件时按扩展名筛选 —— **不含 `.h`**（理由见模块 docstring 第 3 条）。
_SOURCE_EXTS = ("*.c", "*.cpp", "*.cc", "*.ino")

#: 传给缓存 key 的"依赖文件"扩展名：include 目录下这些文件的内容变化
#: 会让分析结果失效。
_HEADER_EXTS = (".h", ".hpp", ".hh", ".inc")

#: 这些 id 属"元信息"，不是代码问题：cppcheck 在报告自己的运行状态。
_META_IDS = frozenset({
    "checkersReport",
    "normalCheckLevelMaxBranches",
    "toomanyconfigs",
    "unmatchedSuppression",
    "invalidSuppression",
    "missingInclude",
    "missingIncludeSystem",
    "missingIncludeExplicit",
    "syntaxError",           # 单独处理：它是 error，但含义是"没读进去"
})

#: exe 路径 → `--errorlist` 的 id 集合（进程内缓存，避免每轮起子进程）。
_KNOWN_IDS: dict[str, frozenset[str]] = {}


@dataclass
class CppcheckIssue:
    """一条 cppcheck 诊断（字段与模板一一对应，不做裁剪）。"""

    file: str = ""
    line: int = 0
    column: int = 0
    severity: str = ""
    id: str = ""
    message: str = ""
    #: 落点在厂家 SDK / 第三方库里（不在用户可控代码里）。
    #: 这类诊断**照原样报告**，但不参与阻断判定 —— CMSIS / HAL 是官方发布的
    #: 代码，它过不过 cppcheck 与用户的固件对不对无关；让它们阻断构建，
    #: 等于所有 STM32 工程永远红着。
    vendor: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def where(self) -> str:
        if self.file in ("", "nofile"):
            return "nofile"
        return f"{self.file}:{self.line}" if self.line else self.file


@dataclass
class CppcheckReport:
    """一次静态分析的完整结果。

    `issues` 只放**代码问题**（severity != information）；cppcheck 自己
    的运行状态进 `meta`；解析不了的行进 `unparsed`（原文保留，不丢）。
    """

    ok: bool = False
    status: str = "not_run"        # ran | cached | timeout | crashed | skipped | no_files
    skip_reason: str = ""
    issues: list[CppcheckIssue] = field(default_factory=list)
    meta: list[CppcheckIssue] = field(default_factory=list)
    unparsed: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    raw: str = ""
    command: list[str] = field(default_factory=list)
    elapsed_ms: float = 0.0
    cached: bool = False
    headers_skipped: int = 0
    vendor_roots: list[str] = field(default_factory=list)

    # -- 分类视图 ---------------------------------------------------------
    @property
    def blocking(self) -> list[CppcheckIssue]:
        """severity=error **且落在用户代码里** —— 这些才是闸门。

        厂家 SDK 里的 error 单独归 `vendor_errors`：照实报告，不阻断
        （理由见 `CppcheckIssue.vendor`）。
        """
        return [i for i in self.issues
                if i.severity in BLOCKING_SEVERITIES and not i.vendor]

    @property
    def vendor_errors(self) -> list[CppcheckIssue]:
        return [i for i in self.issues
                if i.severity in BLOCKING_SEVERITIES and i.vendor]

    @property
    def warnings(self) -> list[CppcheckIssue]:
        return [i for i in self.issues if i.severity == "warning"]

    @property
    def styles(self) -> list[CppcheckIssue]:
        return [i for i in self.issues
                if i.severity in ("style", "performance", "portability")]

    def buckets(self) -> list[tuple[str, int]]:
        """按 id 分桶计数，次数降序。措辞层面的"potential issues"没有信息量。"""
        counts: dict[str, int] = {}
        for issue in self.issues:
            counts[issue.id or "?"] = counts.get(issue.id or "?", 0) + 1
        return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))

    def summary_line(self) -> str:
        """一行可用作日志前缀的描述 —— 区分"没跑成"与"跑了且干净"。"""
        if not self.ok:
            return f"静态分析未完成（{self.status}）{('：' + self.skip_reason) if self.skip_reason else ''}"
        parts = [f"{len(self.issues)} 条诊断",
                 f"error {len(self.blocking)}",
                 f"warning {len(self.warnings)}",
                 f"style {len(self.styles)}"]
        if self.vendor_errors:
            parts.append(f"厂家库 error {len(self.vendor_errors)}（不阻断）")
        if self.headers_skipped:
            parts.append(f"未单独分析 .h {self.headers_skipped} 个")
        if self.unparsed:
            # 解析不了的行不进任何统计。**必须在这里出现**，否则模板失效时
            # 整份输出会退化成"0 条诊断"——和闸门失效是同一类错误。
            parts.append(f"未解析 {len(self.unparsed)} 行")
        if self.cached:
            parts.append("缓存命中")
        return " / ".join(parts)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "status": self.status,
            "skip_reason": self.skip_reason,
            "issues": [i.as_dict() for i in self.issues],
            "meta": [i.as_dict() for i in self.meta],
            "unparsed": list(self.unparsed),
            "notes": list(self.notes),
            "buckets": [{"id": k, "count": v} for k, v in self.buckets()],
            "elapsed_ms": round(self.elapsed_ms, 1),
            "cached": self.cached,
            "headers_skipped": self.headers_skipped,
            "command": list(self.command),
        }


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def run_cppcheck(source_dir: str, *,
                 include_dirs: Sequence[str] = (),
                 defines: Sequence[str] = (),
                 force_includes: Sequence[str] = (),
                 vendor_roots: Sequence[str] = (),
                 enable: str = "all",
                 timeout: float = DEFAULT_TIMEOUT_S,
                 use_cache: bool = True,
                 exe: Path | None = None) -> CppcheckReport:
    """对源码目录跑一次 cppcheck。

    Args:
        source_dir: 源码目录。
        include_dirs: 编译用的头文件搜索路径（**与编译同一份**，否则
            `missingInclude` 会让 `#if` 分支判定失真）。
        defines: 编译用的宏（不带 `-D` 前缀）。
        force_includes: 强制包含的头文件。用途是把**编译器的内建宏**
            （`__GNUC__` / `__arm__` / `__ARM_ARCH_7EM__` …）喂给 cppcheck：
            它自己不预定义这些，缺了会走进 CMSIS 的 `#error Unknown compiler`。
            见 `firmforge.providers.cppcheck_support.predefines_header()`。
        vendor_roots: 厂家 SDK / 第三方库的根目录。落在这些目录里的诊断
            **照原样保留**（在 `issues` 里带 `vendor=True`），但不触发阻断。
        enable: cppcheck `--enable` 取值。
        timeout: 单次上限（秒）。超时会被如实上报，不会伪装成"没问题"。
        use_cache: 命中内容哈希缓存就直接返回（派生物，可安全删除）。
        exe: 指定 cppcheck 可执行文件（测试注入用）。

    Returns:
        `CppcheckReport`。**失败也是返回值**，不抛异常给上层吞掉。
    """
    start = time.perf_counter()
    report = CppcheckReport()

    cppcheck_exe = Path(exe) if exe else _find_cppcheck()
    if not cppcheck_exe:
        report.status = "skipped"
        report.skip_reason = "cppcheck 未安装（winget install Cppcheck.Cppcheck）"
        return report

    src = Path(source_dir)
    files, headers_skipped = _collect_sources(src)
    report.headers_skipped = headers_skipped
    if not files:
        report.status = "no_files"
        report.skip_reason = f"{src} 下没有 .c/.cpp/.ino 文件"
        report.ok = True          # 没东西可查 ≠ 查失败
        return report

    cmd = _build_command(cppcheck_exe, files, include_dirs=include_dirs,
                         defines=defines, force_includes=force_includes,
                         enable=enable)
    report.command = cmd

    version = _cppcheck_version(cppcheck_exe)
    key = _cache_key(cmd, version, src, include_dirs, vendor_roots)
    if use_cache:
        hit = _cache_load(key)
        if hit is not None:
            report = hit
            report.cached = True
            report.status = "cached"
            report.elapsed_ms = (time.perf_counter() - start) * 1000
            return report

    note = _degradation_note(include_dirs, defines, force_includes)
    if note:
        report.notes.append(note)

    try:
        r = run_text(cmd, timeout=timeout, cwd=str(src))
    except Exception as exc:                      # 含 TimeoutExpired
        report.ok = False
        report.status = ("timeout" if exc.__class__.__name__ == "TimeoutExpired"
                         else "crashed")
        report.skip_reason = f"{type(exc).__name__}: {exc}"
        report.elapsed_ms = (time.perf_counter() - start) * 1000
        # 超时也要留下现场：上一次的 stderr 可能是唯一线索，但这里拿不到，
        # 所以至少把命令原样带出去，让调用方可以自己重跑。
        report.notes.append(
            f"cppcheck 未在 {timeout:.0f}s 内完成 —— 本次静态分析没有结论。"
            "不要把它读成'没有发现问题'。")
        logger.warning("Cppcheck %s: %s", report.status, exc)
        return report

    report.raw = _compose_raw(r.stdout or "", r.stderr or "")
    _parse_into(report, r.stdout or "", r.stderr or "")
    report.vendor_roots = [str(v) for v in vendor_roots]
    _mark_vendor(report)
    report.ok = True
    report.status = "ran"
    report.elapsed_ms = (time.perf_counter() - start) * 1000

    # 抑制项写错必须自己暴露（`--suppress` 拼错在旧版里是静默的）。
    #
    # 判据是 **id 在不在 cppcheck 的规则清单里**，不是"这次有没有命中"：
    # 一个名字正确的抑制项本来就可能这一轮没触发（unusedFunction 在没定义
    # 函数的文件上就不会命中），把它当错误报等于天天喊狼来了。
    unknown = _unknown_suppressions(cppcheck_exe, report)
    if unknown:
        report.notes.append(
            "抑制 id 在 cppcheck 的规则清单里不存在（拼错或已改名）："
            + ", ".join(unknown)
            + " —— 这类抑制项压不住任何东西，噪声会照常进入计数，"
              "而日志表面上一切正常。以 `cppcheck --errorlist` 里的 id 为准。")
    if any(m.id in ("missingInclude", "missingIncludeSystem",
                    "missingIncludeExplicit") for m in report.meta):
        report.notes.append(
            "cppcheck 有未找到的头文件（missingInclude）：相关 TU 里的 "
            "#if 分支可能按'宏未定义'取值，结论带水分。"
            "修法是把编译用的 -I 传进来（各平台提供者的 cppcheck_context()）。")
    if any(m.id == "invalidSuppression" for m in report.meta):
        report.notes.append(
            "cppcheck 抑制指令写法不对（invalidSuppression）。正确形态："
            "// cppcheck-suppress <id>   —— 必须紧贴**下一行**语句，"
            "或 // cppcheck-suppress <id> 放在文件内第一条语句之前；"
            "`// cppcheck-suppress-file <id>` 必须是**文件第一行**，"
            "且指令后只允许空白与 id，不要追加中文说明。")
    if any(m.id == "syntaxError" for m in report.meta):
        report.notes.append(
            "cppcheck 报了 syntaxError（该文件没被解析进去）——"
            "这个文件的其余诊断全部不存在，不能当作'干净'。"
            "`.ino` 缺函数原型时也会走到这里。")
    if report.unparsed:
        report.notes.append(
            f"cppcheck 有 {len(report.unparsed)} 行输出不符合 `--template` 的"
            "制表符格式，原文保留在 raw 里但没有计入任何统计。"
            "**若这个数接近全量，说明模板没生效、本次闸门不可信** —— "
            "上一版就是因为解析错位，`#error` 被打成 severity='161'，"
            "日志照样报 0 errors。")

    if report.ok and use_cache:
        _cache_store(key, report, version)

    return report


# ---------------------------------------------------------------------------
# 命令行构造
# ---------------------------------------------------------------------------

def _build_command(exe: Path, files: Iterable[str], *,
                   include_dirs: Sequence[str],
                   defines: Sequence[str],
                   force_includes: Sequence[str],
                   enable: str) -> list[str]:
    cmd = [
        str(exe),
        "--enable=" + enable,
        "--template=" + _TEMPLATE,
        "--inline-suppr",
        "--quiet",
    ]
    for sup in DEFAULT_SUPPRESS:
        cmd.append("--suppress=" + sup)
    for inc in force_includes:
        cmd.append("--include=" + inc)
    for d in defines:
        cmd.append("-D" + d)
    for inc in include_dirs:
        cmd.extend(["-I", inc])
    cmd.extend(files)
    return cmd


def _collect_sources(src: Path) -> tuple[list[str], int]:
    """收集**翻译单元**（.c/.cpp/.ino）。返回 (文件列表, 被跳过的 .h 数)。

    头文件不单独分析：它不是 TU，脱离包含者上下文后 `unusedStructMember`
    必然全报、`#if` 分支判定也会失真（见模块 docstring）。
    """
    if not src.exists():
        return [], 0
    files: list[str] = []
    seen: set[str] = set()
    for ext in _SOURCE_EXTS:
        for f in sorted(src.rglob(ext)):
            if not f.is_file():
                continue
            if any(part.startswith(".") for part in f.relative_to(src).parts):
                continue
            p = str(f.resolve())
            if p not in seen:
                seen.add(p)
                files.append(p)
    headers = sum(1 for ext in ("*.h", "*.hpp")
                  for f in src.rglob(ext) if f.is_file())
    return _to_native_paths(files), headers


# ---------------------------------------------------------------------------
# 输出解析 —— 制表符分隔，路径里的冒号不参与切分
# ---------------------------------------------------------------------------

def _compose_raw(stdout: str, stderr: str) -> str:
    """原始输出（stdout + stderr），供 `--json` 透传给调用方。"""
    return (f"--- stdout ---\n{stdout}\n--- stderr ---\n{stderr}").strip()


def _parse_into(report: CppcheckReport, stdout: str, stderr: str) -> None:
    for text in (stderr, stdout):          # cppcheck 写 stderr，stdout 一般为空
        for raw in text.splitlines():
            _classify(raw, report)


def _classify(raw: str, report: CppcheckReport) -> None:
    line = raw.rstrip("\r")
    if not line.strip():
        return
    parts = line.split("\t", 5)
    if len(parts) != 6:
        # 模板没生效（或 cppcheck 吐了别的行）。**原文保留**，
        # 不做"猜字段"的二次解析 —— 上一次正是猜错了才把闸门弄哑。
        report.unparsed.append(line)
        return

    file, line_no, col, severity, rule_id, message = parts
    issue = CppcheckIssue(
        file=file,
        line=int(line_no) if line_no.isdigit() else 0,
        column=int(col) if col.isdigit() else 0,
        severity=severity.strip(),
        id=rule_id.strip(),
        message=message.strip(),
    )
    if issue.severity == "information" or issue.id in _META_IDS:
        report.meta.append(issue)
    else:
        report.issues.append(issue)


def _mark_vendor(report: CppcheckReport) -> None:
    """把落点在厂家 SDK 里的诊断标成 `vendor`（照实保留，不参与阻断）。"""
    roots = [str(Path(r)).replace("\\", "/").rstrip("/").lower()
             for r in report.vendor_roots if r]
    if not roots:
        return
    for issue in report.issues:
        target = str(issue.file).replace("\\", "/").lower()
        if any(target.startswith(root + "/") for root in roots):
            issue.vendor = True


def _unmatched_hint(report: CppcheckReport) -> str:
    """从原始输出里挑出"哪个抑制项没命中"。

    cppcheck 的 `unmatchedSuppression` message 形如
    ``Unmatched suppression: constParameter``。
    """
    names: list[str] = []
    for m in report.meta:
        if m.id != "unmatchedSuppression":
            continue
        found = re.search(r"suppression[s]?:\s*(\S+)", m.message)
        if found:
            names.append(found.group(1))
    return ", ".join(sorted(set(names)))


def _known_rule_ids(exe: Path) -> frozenset[str]:
    """cppcheck 认识的规则 id 全集（`--errorlist` 是唯一权威清单）。

    用来区分两种 `unmatchedSuppression`：
      · id **不在**清单里 → 抑制项写错了（改名/拼错），必须报出来；
      · id 在清单里但本轮没命中 → 正常，不报（否则天天喊狼来了）。
    """
    cache = _KNOWN_IDS.get(str(exe))
    if cache is not None:
        return cache
    ids: set[str] = set()
    try:
        r = run_text([str(exe), "--errorlist"], timeout=60)
        ids = set(re.findall(r'id="([A-Za-z0-9_]+)"', (r.stdout or "") + (r.stderr or "")))
    except Exception:
        ids = set()
    # `--suppress=` 还接受几个不是"消息 id"的伪 id；未取到清单时宁可空集，
    # 空集会让 `_unknown_suppressions` 保持沉默（不误报）。
    ids |= {"unmatchedSuppression", "invalidSuppression", "missingIncludeSystem"}
    frozen = frozenset(ids)
    _KNOWN_IDS[str(exe)] = frozen
    return frozen


def _unknown_suppressions(exe: Path, report: CppcheckReport) -> list[str]:
    """本轮里"名字根本不存在"的抑制项（含 cppcheck 自己点名的那些）。"""
    known = _known_rule_ids(exe)
    if not known:
        return []
    suspects = set(DEFAULT_SUPPRESS)
    hint = _unmatched_hint(report)
    if hint:
        suspects |= {s.strip() for s in hint.split(",") if s.strip()}
    return sorted(s for s in suspects if s not in known)


# ---------------------------------------------------------------------------
# 缓存 —— 内容哈希，派生物可安全删除
# ---------------------------------------------------------------------------

def _cache_root() -> Path:
    from firmforge.infrastructure import paths
    return paths.cache_dir() / "cppcheck"


def _cache_key(cmd: Sequence[str], version: str, src: Path,
               include_dirs: Sequence[str],
               vendor_roots: Sequence[str] = ()) -> str:
    """缓存键 = 命令行 + cppcheck 版本 + 输入文件内容 + include 目录里的头文件内容。

    为什么不只哈希命令行：cppcheck 的输入是**文件内容**，不是路径。
    为什么连 include 目录下的头文件也哈希：头文件变了，同一个 .c 的分析结果
    会变。只按版本号路径判断"SDK 没变"是假设，不是证据。
    """
    h = hashlib.sha256()
    h.update(version.encode("utf-8"))
    h.update(json.dumps(list(cmd), ensure_ascii=False).encode("utf-8"))
    h.update(json.dumps(list(vendor_roots), ensure_ascii=False).encode("utf-8"))
    for path in _cache_inputs(src, include_dirs):
        h.update(str(path).encode("utf-8"))
        try:
            h.update(hashlib.sha256(path.read_bytes()).digest())
        except OSError:
            h.update(b"<unreadable>")
    return h.hexdigest()


def _cache_inputs(src: Path, include_dirs: Sequence[str]) -> list[Path]:
    out: list[Path] = []
    for ext in _SOURCE_EXTS:
        out.extend(f for f in src.rglob(ext) if f.is_file())
    for inc in include_dirs:
        base = Path(inc)
        if not base.is_dir():
            continue
        for header in base.rglob("*"):
            if header.is_file() and header.suffix.lower() in _HEADER_EXTS:
                out.append(header)
    return out


def _cache_path(key: str) -> Path:
    return _cache_root() / key[:2] / f"{key}.json"


def _cache_load(key: str) -> CppcheckReport | None:
    path = _cache_path(key)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema") != "ff.cppcheck/1":
            return None
        data = payload["report"]
        report = CppcheckReport(
            ok=bool(data.get("ok")),
            status="cached",
            skip_reason=data.get("skip_reason", ""),
            issues=[CppcheckIssue(**i) for i in data.get("issues", [])],
            meta=[CppcheckIssue(**i) for i in data.get("meta", [])],
            unparsed=list(data.get("unparsed", [])),
            notes=list(data.get("notes", [])),
            raw=data.get("raw", ""),
            command=list(data.get("command", [])),
            headers_skipped=int(data.get("headers_skipped", 0)),
            vendor_roots=list(data.get("vendor_roots", [])),
        )
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return report


def _cache_store(key: str, report: CppcheckReport, version: str) -> None:
    if not report.ok:
        return                      # 失败不缓存：下次必须重新跑
    path = _cache_path(key)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema": "ff.cppcheck/1",
            "cppcheck_version": version,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "report": {"ok": report.ok, "status": "ran",
                       "skip_reason": report.skip_reason,
                       "issues": [i.as_dict() for i in report.issues],
                       "meta": [i.as_dict() for i in report.meta],
                       "unparsed": report.unparsed,
                       "notes": report.notes,
                       "raw": report.raw,
                       "command": report.command,
                       "headers_skipped": report.headers_skipped,
                       "vendor_roots": report.vendor_roots},
        }
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False) + "\n",
                       encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        logger.debug("Cppcheck cache write failed: %s", exc)


def _degradation_note(include_dirs: Sequence[str], defines: Sequence[str],
                      force_includes: Sequence[str] = ()) -> str:
    """没有 include / 宏时**必须说出来** —— 否则调用方会把带水分的结论当事实。"""
    missing = []
    if not include_dirs:
        missing.append("-I")
    if not defines:
        missing.append("-D")
    if not force_includes:
        missing.append("编译器内建宏（--include）")
    if not missing:
        return ""
    return ("未向 cppcheck 提供 " + " / ".join(missing)
            + "：`#include` 找不到的头文件会让该 TU 的 `#if` 分支按「宏未定义」"
              "取值，按编译器分支的头文件还会落到 `#else` 的 `#error`。"
              "此时的诊断只反映预处理后的残缺视图。")


# ---------------------------------------------------------------------------
# 工具定位
# ---------------------------------------------------------------------------

def _find_cppcheck() -> Path | None:
    """Locate cppcheck.exe on PATH or in toolchain directory."""
    import shutil

    found = shutil.which("cppcheck")
    if found:
        return Path(found)

    from firmforge.infrastructure import paths
    toolchain = paths.toolchains_dir() / "cppcheck"
    exe = toolchain / "cppcheck.exe"
    if exe.exists():
        return exe

    for loc in [
        Path.home() / "AppData" / "Local" / "Microsoft" / "WinGet" / "Packages",
        Path("C:/") / "Program Files" / "Cppcheck",
    ]:
        for f in loc.rglob("cppcheck.exe"):
            return f

    return None


def _cppcheck_version(exe: Path) -> str:
    """`Cppcheck 2.21.0` → `2.21.0`。进缓存键：换版本必须重跑。"""
    try:
        r = run_text([str(exe), "--version"], timeout=10)
        text = (r.stdout or "") + (r.stderr or "")
        m = re.search(r"(\d+\.\d+(?:\.\d+)?)", text)
        return m.group(1) if m else text.strip()
    except Exception:
        return "unknown"


def _to_native_paths(paths: list[str]) -> list[str]:
    """Convert paths for native Windows tool (MSYS2 /c/ → C:\\)."""
    import os as _os
    if _os.name != "nt":
        return paths

    result: list[str] = []
    for p in paths:
        if p.startswith("/") and len(p) > 2 and p[2] == "/":
            try:
                r = run_text(["cygpath", "-w", p], timeout=2)
                if r.returncode == 0 and r.stdout.strip():
                    result.append(r.stdout.strip())
                    continue
            except Exception:
                pass
        result.append(p)
    return result


__all__ = [
    "CppcheckIssue", "CppcheckReport", "run_cppcheck",
    "DEFAULT_SUPPRESS", "DEFAULT_TIMEOUT_S", "BLOCKING_SEVERITIES",
]
