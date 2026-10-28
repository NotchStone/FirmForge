"""阶段独立命令：`ff review` / `ff flash` / `ff verify`。

设计原则（2026-10-27 用户提出）：**每个阶段一个命令**，而不是给 `ff run`
堆 `--skip-review` 之类的开关。理由：
  · 端到端是 `ff run` 存在的唯一理由，加跳过开关会让这个承诺破裂；
  · 用户的实际诉求是「改完代码只想烧，不想重跑 100 秒 cppcheck」，
    这是命令粒度问题，不是参数问题。

三条硬约束（本文件负责守住）：
  ① 独立命令**只跑那一个阶段**（外加 S1 解析板卡），不能偷偷把整条流程带上；
  ② 独立命令与 `ff run` **共用同一份 state.json**，否则「烧过了但仍显示没烧」；
  ③ 定位固件**绝不猜**：多份就报错列候选。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from firmforge.adapters import cli
from firmforge.core.pipeline_runner import PipelineRunner, PipelineStage


def _ok(stage: int, name: str) -> PipelineStage:
    s = PipelineStage(stage=stage, name=name)
    s.success = True
    s.elapsed_ms = 1.0
    return s


@pytest.fixture()
def stub_stages(monkeypatch):
    """记录每个阶段被调了几次，全部返回成功。"""
    calls: list[str] = []

    def fake_detect(self, board_id):                       # noqa: ANN001
        calls.append("detect")
        s = _ok(1, "Detect")
        s.details = {"board_id": board_id or "gc_h743",
                     "config": {"platform": "stm32",
                                "mcu": {"chip": "stm32h743zit6"}}}
        return s

    def fake_review(self, board_id, source_dir, cfg):       # noqa: ANN001
        calls.append("review")
        return _ok(2, "Review")

    def fake_build(self, board_id, source_dir):             # noqa: ANN001
        calls.append("build")
        s = _ok(3, "Build")
        s.details = {"firmware_path": ""}
        return s

    def fake_flash(self, board_id, fw):                     # noqa: ANN001
        calls.append("flash")
        s = _ok(4, "Flash")
        s.details = {"bytes_written": 100, "firmware_path": fw}
        return s

    def fake_verify(self, board_id, expected="", **kw):     # noqa: ANN001
        calls.append("verify")
        s = _ok(5, "Verify")
        s.verdict = "verified"
        return s

    monkeypatch.setattr(PipelineRunner, "_stage_detect", fake_detect)
    monkeypatch.setattr(PipelineRunner, "_stage_review", fake_review)
    monkeypatch.setattr(PipelineRunner, "_stage_build", fake_build)
    monkeypatch.setattr(PipelineRunner, "_stage_flash", fake_flash)
    monkeypatch.setattr(PipelineRunner, "_stage_verify", fake_verify)
    return calls


def _ns(**kw) -> argparse.Namespace:
    base = dict(board="gc_h743", app=None, apps="", firmware=None, expected="",
                boards_dir=None, workspace=None, json=False,
                open_panel="none", panel_wait=0)
    base.update(kw)
    return argparse.Namespace(**base)


# ---------------------------------------------------------------------------
# 只跑一个阶段
# ---------------------------------------------------------------------------


def test_review_runs_only_s1_and_s2(stub_stages, tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    assert cli.cmd_review(_ns(app=str(app), workspace=str(tmp_path))) == 0
    assert stub_stages == ["detect", "review"], \
        f"ff review 不该带上 Build/Flash/Verify：{stub_stages}"


def test_verify_runs_only_s1_and_s5(stub_stages, tmp_path):
    assert cli.cmd_verify(_ns(workspace=str(tmp_path), expected="HB")) == 0
    assert stub_stages == ["detect", "verify"], \
        f"ff verify 不该重新编译或烧录：{stub_stages}"


def test_flash_runs_only_s1_and_s4(stub_stages, tmp_path):
    hexf = tmp_path / "firmware.hex"
    hexf.write_text(":00000001FF\n", encoding="utf-8")
    assert cli.cmd_flash(_ns(firmware=str(hexf), workspace=str(tmp_path))) == 0
    assert stub_stages == ["detect", "flash"], \
        f"ff flash 不该跑 Review/Build：{stub_stages}"


def test_run_still_runs_everything(stub_stages, tmp_path):
    """`ff run` 保持端到端 —— 这是它存在的理由，不能被改成可选。"""
    app = tmp_path / "app"
    app.mkdir()
    (app / "main.c").write_text("int main(void){return 0;}", encoding="utf-8")
    cli.cmd_run(_ns(app=str(app), workspace=str(tmp_path), panel_wait=0))
    assert stub_stages == ["detect", "review", "build", "flash", "verify"]


# ---------------------------------------------------------------------------
# 状态共享：ff flash 之后 ff run 必须知道「已经烧过」
# ---------------------------------------------------------------------------


def test_flash_updates_state_json(stub_stages, tmp_path):
    hexf = tmp_path / "firmware.hex"
    hexf.write_text(":00000001FF\n", encoding="utf-8")
    cli.cmd_flash(_ns(firmware=str(hexf), workspace=str(tmp_path)))

    state_file = tmp_path / ".ff-run" / "state.json"
    assert state_file.is_file(), "ff flash 必须写 state.json"
    data = json.loads(state_file.read_text(encoding="utf-8"))
    assert data["stages"]["flash"]["status"] == "done", \
        "旧实现不碰 state —— 于是 ff flash 之后 ff run 会再烧一遍"


# ---------------------------------------------------------------------------
# 固件定位：绝不猜
# ---------------------------------------------------------------------------


def _fake_cache(monkeypatch, tmp_path: Path) -> Path:
    from firmforge.infrastructure import paths
    cache = tmp_path / "cache" / "build"
    monkeypatch.setattr(paths, "build_cache_dir", lambda: cache)
    return cache


def test_multiple_hex_refuses_to_guess(stub_stages, tmp_path, monkeypatch, capsys):
    """缓存里有多份 hex 时报错列候选 —— **不按修改时间挑最新**。

    猜错的代价不是「看到错答案」，是把**别的项目**的固件烧进板子。
    """
    cache = _fake_cache(monkeypatch, tmp_path)
    for name in ("app", "hello_blink"):
        d = cache / "gc_h743" / name
        d.mkdir(parents=True)
        (d / "firmware.hex").write_text(":00000001FF\n", encoding="utf-8")

    code = cli.cmd_flash(_ns(workspace=str(tmp_path)))
    out = capsys.readouterr().out
    assert code == 1
    assert "app" in out and "hello_blink" in out
    assert "flash" not in stub_stages, "定位不唯一时绝不能烧"


def test_single_hex_in_cache_is_used(stub_stages, tmp_path, monkeypatch):
    cache = _fake_cache(monkeypatch, tmp_path)
    d = cache / "gc_h743" / "app"
    d.mkdir(parents=True)
    (d / "firmware.hex").write_text(":00000001FF\n", encoding="utf-8")

    assert cli.cmd_flash(_ns(workspace=str(tmp_path))) == 0
    assert "flash" in stub_stages


def test_app_name_selects_among_many(stub_stages, tmp_path, monkeypatch):
    cache = _fake_cache(monkeypatch, tmp_path)
    for name in ("app", "hello_blink"):
        d = cache / "gc_h743" / name
        d.mkdir(parents=True)
        (d / "firmware.hex").write_text(":00000001FF\n", encoding="utf-8")

    assert cli.cmd_flash(_ns(app="hello_blink", workspace=str(tmp_path))) == 0
    assert "flash" in stub_stages


def test_missing_hex_explains_what_to_do(stub_stages, tmp_path, monkeypatch, capsys):
    _fake_cache(monkeypatch, tmp_path)
    code = cli.cmd_flash(_ns(workspace=str(tmp_path)))
    out = capsys.readouterr().out
    assert code == 1
    assert "ff build" in out, "报错要给下一步动作，不能只说找不到"


# ---------------------------------------------------------------------------
# ff status
# ---------------------------------------------------------------------------


def test_status_on_empty_state(tmp_path, capsys):
    code = cli.cmd_status(_ns(workspace=str(tmp_path)))
    out = capsys.readouterr().out
    assert code == 0
    assert "空" in out


def test_status_reports_fingerprints_and_stages(tmp_path, capsys):
    from firmforge.core.pipeline_state import PipelineState

    st = PipelineState(tmp_path)
    st.mark_done("build", hex=str(tmp_path / "firmware.hex"))
    st.update_fingerprints({"board_id": "gc_h743", "source": "abc123",
                            "hex": "def456", "port": "COM7"})
    st.save()

    code = cli.cmd_status(_ns(workspace=str(tmp_path)))
    out = capsys.readouterr().out
    assert code == 0
    assert "gc_h743" in out
    assert "build" in out
    # 绝对路径才点得开
    assert str(tmp_path) in out


def test_status_explains_stale_last_error(tmp_path, capsys):
    """阶段现在是 done 而 last_error 还在 —— 必须说清是更早一次的记录。"""
    from firmforge.core.pipeline_state import PipelineState

    st = PipelineState(tmp_path)
    st.mark_failed("build", "something broke")
    st.mark_done("build", hex=str(tmp_path / "firmware.hex"))
    st.update_fingerprints({"board_id": "gc_h743", "source": "a",
                            "hex": "b", "port": ""})
    st.save()

    cli.cmd_status(_ns(workspace=str(tmp_path)))
    out = capsys.readouterr().out
    assert "done" in out
    assert "更早一次失败" in out, f"会让 done 与 last_error 自相矛盾：{out[:300]}"


# ---------------------------------------------------------------------------
# 显式 --app 必须压过 state 里的旧记录
# ---------------------------------------------------------------------------


def test_app_hint_beats_stale_state_record(stub_stages, tmp_path, monkeypatch):
    """state 记着 hello_blink，但用户点名 `--app app` —— 必须烧 app。

    顺序反了（state 优先）时，`ff flash X --app other` 会安静地烧上一份，
    错误形态与 `ff inspect` 取最新 ELF 那次完全一样：答案看起来合理。
    """
    from firmforge.core.pipeline_state import PipelineState

    cache = _fake_cache(monkeypatch, tmp_path)
    rec = cache / "gc_h743" / "hello_blink"
    rec.mkdir(parents=True)
    stale = rec / "firmware.hex"
    stale.write_text(":00000001FF\n", encoding="utf-8")

    want = cache / "gc_h743" / "app"
    want.mkdir(parents=True)
    (want / "firmware.hex").write_text(":00000001FF\n", encoding="utf-8")

    st = PipelineState(tmp_path)
    st.mark_done("build", hex=str(stale))
    st.save()

    flashed: list[str] = []
    monkeypatch.setattr(PipelineRunner, "_stage_flash",
                        lambda self, b, fw: (flashed.append(fw), _ok(4, "Flash"))[1])

    assert cli.cmd_flash(_ns(app="app", workspace=str(tmp_path))) == 0
    assert flashed and "app" in flashed[0] and "hello_blink" not in flashed[0], \
        f"烧的是 {flashed}，用户明确要的是 app"


def test_app_hint_without_artifact_does_not_fall_back(stub_stages, tmp_path,
                                                      monkeypatch, capsys):
    """点名了 --app 但缓存里没有它 —— 报错，**不许**退回 state 那份。"""
    from firmforge.core.pipeline_state import PipelineState

    cache = _fake_cache(monkeypatch, tmp_path)
    rec = cache / "gc_h743" / "hello_blink"
    rec.mkdir(parents=True)
    stale = rec / "firmware.hex"
    stale.write_text(":00000001FF\n", encoding="utf-8")

    st = PipelineState(tmp_path)
    st.mark_done("build", hex=str(stale))
    st.save()

    code = cli.cmd_flash(_ns(app="nope", workspace=str(tmp_path)))
    out = capsys.readouterr().out
    assert code == 1
    assert "flash" not in stub_stages, "找不到指定应用时不能改烧别的"
    assert "hello_blink" in out, "报错要列出缓存里到底有什么"


# ---------------------------------------------------------------------------
# S5 面板等待：没有人看着就别无限等
# ---------------------------------------------------------------------------


class _Tty:
    def isatty(self) -> bool:
        return True

    def write(self, _s: str) -> None:
        pass

    def flush(self) -> None:
        pass


def _clean_env(monkeypatch) -> None:
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("SSH_CONNECTION", raising=False)


class _Pipe:
    def isatty(self) -> bool:
        return False

    def write(self, _s: str) -> None:
        pass

    def flush(self) -> None:
        pass


def test_panel_wait_is_zero_when_stdout_is_piped(monkeypatch):
    """管道 / 子进程里 `ff run` 必须会结束。

    2026-10-28 实测：五个阶段 44 秒跑完，然后挂在 `join()` 里 400 秒 ——
    对 CI 和 Agent 调用方，这就是「命令永不返回」。
    """
    import sys
    _clean_env(monkeypatch)
    monkeypatch.setattr(sys, "stdout", _Pipe())
    assert cli._resolve_panel_wait(_ns(panel_wait=None)) == 0.0


def test_panel_wait_is_infinite_on_a_real_terminal(monkeypatch):
    """人在终端前看时保持原行为：等他点 Stop。"""
    import sys
    _clean_env(monkeypatch)
    monkeypatch.setattr(sys, "stdout", _Tty())
    assert cli._resolve_panel_wait(_ns(panel_wait=None)) is None


def test_explicit_panel_wait_wins(monkeypatch):
    import sys
    _clean_env(monkeypatch)
    monkeypatch.setattr(sys, "stdout", _Tty())
    assert cli._resolve_panel_wait(_ns(panel_wait=120)) == 120
    assert cli._resolve_panel_wait(_ns(panel_wait=0)) == 0


def test_json_mode_never_waits_for_panel(monkeypatch):
    import sys
    _clean_env(monkeypatch)
    monkeypatch.setattr(sys, "stdout", _Tty())
    assert cli._resolve_panel_wait(_ns(json=True, panel_wait=None)) == 0.0


def test_ci_env_never_waits_for_panel(monkeypatch):
    import sys
    monkeypatch.delenv("SSH_CONNECTION", raising=False)
    monkeypatch.setenv("CI", "true")
    monkeypatch.setattr(sys, "stdout", _Tty())
    assert cli._resolve_panel_wait(_ns(panel_wait=None)) == 0.0


def test_elapsed_desc_separates_panel_wait():
    """流水线耗时与「人什么时候点 Stop」不能混成一个数字。"""
    from firmforge.core.pipeline_runner import PipelineResult

    r = PipelineResult(total_elapsed_ms=44468.0, panel_wait_ms=400000.0)
    text = cli._elapsed_desc(r)
    assert "44468ms" in text
    assert "400.0s" in text and "不计入" in text

    r2 = PipelineResult(total_elapsed_ms=44468.0, panel_wait_ms=0.0)
    assert cli._elapsed_desc(r2) == "44468ms"
