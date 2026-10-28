"""Cppcheck 集成回归 —— 守的是「工具说什么，就原样返回什么」。

这些测试逐条对应 2026-10-27 报出的实际问题。最重的一条是**静态闸门
形同不存在**：源码里明明写着 `#error`，日志仍报 0 errors、BUILD PASSED。
根因不在 cppcheck，在解析层 —— `line.split(":", 3)` 撞上 Windows 盘符冒号，
`severity` 被读成行号 `'161'`，`severity == "error"` 永远不成立。

所以这里的核心断言不是"能解析出字段"，而是**错误必须能抵达阻断判定**。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from firmforge.providers import cppcheck as cc


# --------------------------------------------------------------------------
# 1. 解析：制表符模板 vs 路径里的冒号
# --------------------------------------------------------------------------

def test_windows_path_does_not_shift_fields():
    """`C:\\...\\blackbox.c:161:error:...` 是旧格式，也是闸门失效的现场。

    改成制表符分隔后，路径里的冒号不参与切分，severity 才是真 severity。
    """
    raw = ('C:\\proj\\src\\blackbox.c\t161\t5\terror\t'
           'preprocessorErrorDirective\t#error "bit check failed"')
    report = cc.CppcheckReport()
    cc._classify(raw, report)

    assert len(report.issues) == 1
    issue = report.issues[0]
    assert issue.severity == "error"
    assert issue.id == "preprocessorErrorDirective"
    assert issue.line == 161
    assert issue.file.endswith("blackbox.c")
    # 闸门：这条必须能进来
    assert report.blocking == [issue]


def test_legacy_colon_line_is_kept_raw_and_not_guessed():
    """冒号格式的行**不许猜字段** —— 上一次正是猜错了才把闸门弄哑。"""
    raw = ('C:\\proj\\blackbox.c:161:error:Cppcheck: '
           '#error "bit check failed"')
    report = cc.CppcheckReport(ok=True)
    cc._classify(raw, report)

    assert report.issues == [], "解析不了的行不能被当成诊断"
    assert report.unparsed == [raw], "原文必须保留，否则无从排查"
    assert "未解析 1 行" in report.summary_line()


def test_meta_ids_do_not_pollute_issue_list():
    """`missingInclude` / `unmatchedSuppression` 是运行状态，不是代码问题。"""
    report = cc.CppcheckReport()
    cc._classify("a.c\t1\t0\tinformation\tmissingInclude\tb.h not found", report)
    cc._classify("a.c\t2\t0\terror\tmissingInclude\tb.h not found", report)

    assert report.issues == []
    assert len(report.meta) == 2


# --------------------------------------------------------------------------
# 2. 分桶与措辞：不要说「N potential issues」
# --------------------------------------------------------------------------

def test_buckets_are_by_id_and_sorted():
    report = cc.CppcheckReport(ok=True)
    for _ in range(3):
        report.issues.append(cc.CppcheckIssue(
            severity="style", id="unusedStructMember", message="x"))
    report.issues.append(cc.CppcheckIssue(
        severity="style", id="constVariablePointer", message="y"))

    assert report.buckets() == [("unusedStructMember", 3),
                                ("constVariablePointer", 1)]
    line = report.summary_line()
    assert "error 0" in line and "style 4" in line
    # 「potential issues」这种聚合数字没有信息量，会让 75% 的结构体噪声
    # 看起来像潜在 bug
    assert "potential" not in line


def test_summary_distinguishes_not_run_from_clean():
    """"没跑成"与"跑了且干净"必须一眼可分 —— 旧版都是 0 issues。"""
    failed = cc.CppcheckReport(ok=False, status="timeout",
                               skip_reason="TimeoutExpired: 30s")
    assert "未完成" in failed.summary_line()
    assert "timeout" in failed.summary_line()

    clean = cc.CppcheckReport(ok=True, status="ran")
    assert "未完成" not in clean.summary_line()


# --------------------------------------------------------------------------
# 3. 厂家库诊断：照实报告，但不阻断
# --------------------------------------------------------------------------

def test_vendor_errors_are_reported_but_never_block(tmp_path):
    """CMSIS / HAL 是官方发布的代码，它过不过 cppcheck 与用户固件无关。

    但**不许隐藏** —— 它必须出现在 issues 里（带 vendor 标记），
    否则"工具栏"到"厂家库"的边界就成了信息截留。
    """
    vendor = tmp_path / "packages"
    report = cc.CppcheckReport(ok=True,
                               vendor_roots=[str(vendor)])
    report.issues = [
        cc.CppcheckIssue(file=str(vendor / "cmsis_gcc.h"), line=151,
                         severity="error", id="comparePointers"),
        cc.CppcheckIssue(file=str(tmp_path / "src" / "main.c"), line=42,
                         severity="error", id="nullPointer"),
    ]
    cc._mark_vendor(report)

    assert len(report.issues) == 2, "厂家库诊断不能被丢掉"
    assert [i.id for i in report.vendor_errors] == ["comparePointers"]
    assert [i.id for i in report.blocking] == ["nullPointer"]
    assert "厂家库 error 1（不阻断）" in report.summary_line()


def test_vendor_marking_handles_windows_separators(tmp_path):
    vendor = tmp_path / "packages"
    report = cc.CppcheckReport(ok=True, vendor_roots=[str(vendor)])
    report.issues = [cc.CppcheckIssue(
        file=str(vendor).replace("/", "\\") + "\\cmsis\\x.h",
        severity="error", id="x")]
    cc._mark_vendor(report)
    assert report.issues[0].vendor


# --------------------------------------------------------------------------
# 4. 头文件不是翻译单元
# --------------------------------------------------------------------------

def test_headers_are_not_treated_as_translation_units(tmp_path):
    """`.h` 单独喂给 cppcheck 会在「没有包含者」的上下文里被分析：
    跨 TU 的结构体成员必然全报 `unusedStructMember`（实测 115 条里 86 条），
    而且没有 `-D`，`#if` 分支判定失真。"""
    (tmp_path / "app.c").write_text("int main(void){return 0;}\n",
                                    encoding="utf-8")
    (tmp_path / "bsp.h").write_text("struct s { int a; };\n", encoding="utf-8")

    files, headers = cc._collect_sources(tmp_path)
    assert [Path(f).name for f in files] == ["app.c"]
    assert headers == 1


# --------------------------------------------------------------------------
# 5. 失败是返回值，不是空列表
# --------------------------------------------------------------------------

def test_missing_binary_is_a_reported_skip(monkeypatch):
    monkeypatch.setattr(cc, "_find_cppcheck", lambda: None)
    report = cc.run_cppcheck("/nonexistent")
    assert report.ok is False
    assert report.status == "skipped"
    assert report.skip_reason
    # 关键：不能伪装成"没有问题"
    assert "未完成" in report.summary_line()


def test_timeout_is_reported_not_swallowed(tmp_path, monkeypatch):
    (tmp_path / "a.c").write_text("int main(void){return 0;}\n",
                                  encoding="utf-8")

    def boom(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, 1)

    monkeypatch.setattr(cc, "run_text", boom)
    report = cc.run_cppcheck(str(tmp_path), use_cache=False,
                             exe=Path("cppcheck"))
    assert report.ok is False
    assert report.status == "timeout"
    assert report.command, "超时也要把命令带出去，调用方才能自己重跑"
    assert any("没有结论" in n for n in report.notes)


def test_empty_directory_is_clean_not_failed(tmp_path):
    report = cc.run_cppcheck(str(tmp_path), use_cache=False)
    assert report.status == "no_files"
    assert report.ok is True, "没东西可查 ≠ 查失败"


# --------------------------------------------------------------------------
# 6. 缓存：内容哈希，改一个字节就失效
# --------------------------------------------------------------------------

def test_cache_hits_then_invalidates_on_content_change(tmp_path, monkeypatch):
    from firmforge.providers import textio

    cache = tmp_path / "cache"
    monkeypatch.setattr(cc, "_cache_root", lambda: cache)
    monkeypatch.setattr(cc, "_find_cppcheck", lambda: Path("cppcheck"))
    monkeypatch.setattr(cc, "_cppcheck_version", lambda exe: "2.21.0")
    # 抑制项自检也会起子进程（`--errorlist`）；这里只要缓存行为，
    # 把它挡掉，否则计数会被那一次调用污染。
    monkeypatch.setattr(cc, "_known_rule_ids",
                        lambda exe: frozenset(cc.DEFAULT_SUPPRESS))

    calls = {"n": 0}

    def fake_run(cmd, **kwargs):
        calls["n"] += 1

        class R:
            stdout = ("a.c\t1\t0\tstyle\tconstVariablePointer\tcould be const\n")
            stderr = ""
            returncode = 0

        return R()

    monkeypatch.setattr(cc, "run_text", fake_run)
    src = tmp_path / "src"
    src.mkdir()
    target = src / "a.c"
    target.write_text("int f(int *p){return *p;}\n", encoding="utf-8")

    first = cc.run_cppcheck(str(src), use_cache=True)
    assert first.status == "ran" and calls["n"] == 1

    second = cc.run_cppcheck(str(src), use_cache=True)
    assert second.status == "cached" and second.cached
    assert calls["n"] == 1, "第二次不该再起子进程"
    assert [i.id for i in second.issues] == [i.id for i in first.issues]

    target.write_text("int f(int *p){return *p + 1;}\n", encoding="utf-8")
    third = cc.run_cppcheck(str(src), use_cache=True)
    assert third.status == "ran" and calls["n"] == 2, "内容变了必须重跑"


def test_failed_run_is_never_cached(tmp_path, monkeypatch):
    monkeypatch.setattr(cc, "_cache_root", lambda: tmp_path / "cache")
    monkeypatch.setattr(cc, "_find_cppcheck", lambda: Path("cppcheck"))

    def boom(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, 1)

    monkeypatch.setattr(cc, "run_text", boom)
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.c").write_text("int main(void){return 0;}\n", encoding="utf-8")

    cc.run_cppcheck(str(src), use_cache=True)
    assert not (tmp_path / "cache").exists() or \
        not list((tmp_path / "cache").rglob("*.json"))


# --------------------------------------------------------------------------
# 7. 抑制项自检：拼错的 id 必须自己暴露
# --------------------------------------------------------------------------

def test_suppress_ids_exist_in_cppcheck(monkeypatch):
    """`constParameter` 在 2.21 已拆成 Pointer/Reference/Callback。

    拼错的抑制项既压不住噪声，还会白送一条 `unmatchedSuppression`，
    而日志表面一切正常 —— 所以判据是「id 在不在 `--errorlist` 清单里」。
    """
    exe = cc._find_cppcheck()
    if not exe:
        pytest.skip("本机没有 cppcheck")
    monkeypatch.setattr(cc, "_KNOWN_IDS", {})
    known = cc._known_rule_ids(exe)
    assert len(known) > 100, "`--errorlist` 没解析出来"
    for sup in cc.DEFAULT_SUPPRESS:
        assert sup in known, f"默认抑制项 {sup} 在 cppcheck 的清单里不存在"


def test_unknown_suppression_is_named(monkeypatch):
    """默认抑制项全在清单里、只有 cppcheck 点名的那一个是旧名 → 只报它。

    这条与上一条是同一件事的两面：上一条守「默认项都合法」，这一条守
    「真出现非法项时会被点出来」，而不是静默失效。
    """
    report = cc.CppcheckReport(ok=True)
    report.meta.append(cc.CppcheckIssue(
        severity="information", id="unmatchedSuppression",
        message="Unmatched suppression: constParameter"))
    known = frozenset(cc.DEFAULT_SUPPRESS) | {"constParameterPointer"}
    monkeypatch.setattr(cc, "_known_rule_ids", lambda exe: known)
    assert cc._unknown_suppressions(Path("cppcheck"), report) == ["constParameter"]


# --------------------------------------------------------------------------
# 8. 真跑一次 cppcheck：#error 必须抵达阻断判定
# --------------------------------------------------------------------------

def test_real_cppcheck_reports_error_that_blocks(tmp_path):
    """这一条是整个文件的重点：故意写 `#error`，闸门必须响。"""
    if not cc._find_cppcheck():
        pytest.skip("本机没有 cppcheck")
    src = tmp_path / "src"
    src.mkdir()
    (src / "bsp.c").write_text(
        '#error "bit check failed"\nint main(void){return 0;}\n',
        encoding="utf-8")

    report = cc.run_cppcheck(str(src), use_cache=False)

    assert report.ok is True
    assert report.status == "ran"
    ids = {i.id for i in report.issues}
    assert "preprocessorErrorDirective" in ids, \
        f"#error 没被识别成诊断（实际: {ids} / unparsed: {report.unparsed}）"
    assert report.blocking, "error 级诊断没有进入阻断列表 —— 闸门失效"
    assert report.raw, "原始输出必须透传，否则调用方只能 import 内部 API"


def test_degradation_note_when_no_include_dirs():
    note = cc._degradation_note((), (), ())
    assert "-I" in note and "-D" in note
    assert cc._degradation_note(("/inc",), ("A=1",), ("/x.h",)) == ""
