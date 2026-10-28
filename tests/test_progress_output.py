"""阶段内进度输出：流水线跑的时候必须看得见它在干什么。

2026-10-27 现场：`ff run` 之后 110 秒没有任何输出 —— 因为
`progress_callback` 只在**阶段完成**后触发，而 `cmd_run` 连这个回调都没传。
cppcheck 冷跑一次要 100 秒（CMSIS/HAL 头巨量展开），那段时间屏幕上
一个字都没有，从外面无法区分「在干活」与「卡死」。

两条硬约束：
  ① 进度必须写 **stderr** —— 写 stdout 会被
     `ff run ... | Select-Object -Last 12` 缓冲到进程退出才吐，等于没修；
     而且 `--json` 的 stdout 必须是单个 JSON 对象。
  ② 关键进度行必须在**动作开始之前**出现（「cppcheck 启动」不能等它跑完）。
"""

from __future__ import annotations

import io
import json
import sys

import pytest


# ---------------------------------------------------------------------------
# PipelineRunner.on_note
# ---------------------------------------------------------------------------


class _NoopStage:
    """占位：只测 note 通道，不真的跑任何阶段。"""


def test_note_callback_receives_stage_and_message():
    from firmforge.core.pipeline_runner import PipelineRunner

    seen: list[tuple[str, str]] = []
    r = PipelineRunner(on_note=lambda stage, msg: seen.append((stage, msg)))
    r._note("Review", "cppcheck 启动")
    assert seen == [("Review", "cppcheck 启动")]


def test_note_callback_exception_never_breaks_pipeline():
    """打印失败（管道关闭、编码问题）不该让整条流水线崩掉。"""
    from firmforge.core.pipeline_runner import PipelineRunner

    def boom(stage: str, msg: str) -> None:
        raise UnicodeEncodeError("gbk", "x", 0, 1, "boom")

    r = PipelineRunner(on_note=boom)
    r._note("Review", "随便什么")          # 不抛异常即通过


def test_note_is_optional():
    from firmforge.core.pipeline_runner import PipelineRunner

    r = PipelineRunner()
    r._note("Review", "没人听也要能跑")


def test_count_translation_units(tmp_path):
    from firmforge.core.pipeline_runner import PipelineRunner

    (tmp_path / "a.c").write_text("int a;", encoding="utf-8")
    (tmp_path / "b.cpp").write_text("int b;", encoding="utf-8")
    (tmp_path / "skip.h").write_text("", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "c.c").write_text("int c;", encoding="utf-8")
    assert PipelineRunner._count_translation_units(str(tmp_path)) == 3


def test_review_note_fires_before_cppcheck_returns():
    """「cppcheck 启动」必须在 cppcheck **开始之前**发出，不是之后。"""
    from firmforge.core.pipeline_runner import PipelineRunner

    order: list[str] = []
    r = PipelineRunner(on_note=lambda stage, msg: order.append(msg))

    class _FakeReport:
        ok = True
        status = "ran"
        cached = False
        blocking: list = []
        warnings: list = []
        vendor_errors: list = []
        issues: list = []
        notes: list = []

    def fake_run(*a, **kw):
        order.append("<<cppcheck 真正执行>>")
        return _FakeReport()

    import firmforge.providers.arduino.cppcheck as mod
    original = mod.run_cppcheck
    mod.run_cppcheck = fake_run
    try:
        r._run_cppcheck(None, str(__import__("pathlib").Path.cwd()), {})
    finally:
        mod.run_cppcheck = original

    start = next(i for i, m in enumerate(order) if "cppcheck 启动" in m)
    run = order.index("<<cppcheck 真正执行>>")
    assert start < run, f"启动行必须早于执行：{order}"


# ---------------------------------------------------------------------------
# CLI 侧渲染：stderr，且不污染 stdout
# ---------------------------------------------------------------------------


def test_notes_write_to_stderr(capsys):
    from firmforge.adapters.cli import _Notes

    n = _Notes()
    n.note("Review", "cppcheck 启动（8 个翻译单元）")
    n.stage_done("Review", True, {}, None)

    out, err = capsys.readouterr()
    assert out == "", "进度行绝不能进 stdout"
    assert "[S2" in err
    assert "cppcheck 启动" in err


def test_stage_done_marks_skip_distinctly(capsys):
    """跳过不是通过。`----` / `OK` 混用会让人以为真的跑过了。"""
    from firmforge.adapters.cli import _Notes

    n = _Notes()
    n.stage_done("Build", True, {"skipped": True, "reason": "source unchanged"}, None)
    _out, err = capsys.readouterr()
    assert "SKIP" in err
    assert "source unchanged" in err
    assert " OK " not in err


def test_stage_done_shows_first_error_line(capsys):
    from firmforge.adapters.cli import _Notes

    n = _Notes()
    n.stage_done("Flash", False, {}, "OpenOCD init failed\nTraceback ...")
    _out, err = capsys.readouterr()
    assert "FAIL" in err
    assert "OpenOCD init failed" in err
    assert "Traceback" not in err, "只取第一句，不要把 traceback 铺开"


def test_header_goes_to_stderr(capsys):
    from firmforge.adapters.cli import _Notes

    _Notes().header("gc_h743", "C:/x/app")
    out, err = capsys.readouterr()
    assert out == ""
    assert "gc_h743" in err


def test_json_mode_stdout_stays_pure(tmp_path, capsys):
    """`--json` 的调用方（Agent）必须拿到完整 JSON，不能被进度行插队。"""
    from firmforge.adapters.cli import _Notes, _pipeline_payload
    from firmforge.core.pipeline_runner import PipelineResult, PipelineStage

    n = _Notes()
    n.header("gc_h743", "x")
    n.note("Review", "cppcheck 启动")
    n.stage_done("Review", True, {}, None)

    res = PipelineResult(board="gc_h743", overall_success=True)
    res.stages.append(PipelineStage(stage=1, name="Detect", success=True))
    print(json.dumps(_pipeline_payload(res), ensure_ascii=False))

    out, err = capsys.readouterr()
    payload = json.loads(out)                 # 必须能整体解析
    assert payload["board"] == "gc_h743"
    assert "[S2" in err and "[S2" not in out
