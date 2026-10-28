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
    # panel=None = 没加 `--panel`（默认关闭）。所有阶段命令的单测都走这条默认路径。
    base = dict(board="gc_h743", app=None, apps="", firmware=None, build=None,
                expected="", boards_dir=None, workspace=None, json=False, panel=None)
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
    cli.cmd_run(_ns(app=str(app), workspace=str(tmp_path)))
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

    assert cli.cmd_flash(_ns(build="hello_blink", workspace=str(tmp_path))) == 0
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
    """阶段是 done 而 last_error 还在 —— 必须说清是更早一次的记录。

    这种组合**新代码不会再产生**：``mark_done`` 会顺手擦掉本阶段的
    ``last_error``（否则一轮成功后 ff_status 还报旧错误，等于主动误导）。
    但旧 state 文件里可能留着这种记录，读到时不能把 done 和 last_error
    摆在一起不加解释 —— 所以这里直接注入，而不是走 mark_failed 那条路。
    """
    from firmforge.core.pipeline_state import PipelineState

    st = PipelineState(tmp_path)
    st.mark_done("build", hex=str(tmp_path / "firmware.hex"))
    st.update_fingerprints({"board_id": "gc_h743", "source": "a",
                            "hex": "b", "port": ""})
    st.data["last_error"] = {"stage": "build", "message": "something broke"}
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

    assert cli.cmd_flash(_ns(build="app", workspace=str(tmp_path))) == 0
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

    code = cli.cmd_flash(_ns(build="nope", workspace=str(tmp_path)))
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


def test_panel_is_off_by_default():
    """默认什么都不加 —— 面板功能完全关闭（这是产品定位，不是普通默认值）。

    2026-10-28 用户定调：ff 主要给 Agent 调用，运行完就要返回。
    「默认开着面板、靠调用方记得传 0」已经被证明会挂死（CLI / json / MCP
    三条路里两条漏过），所以默认必须是关。
    """
    assert cli._resolve_panel(_ns()) == ("none", 0.0)


def test_panel_is_off_by_default_even_on_a_real_terminal(monkeypatch):
    """终端在前也不自动开面板：要看就明说，别让默认行为随环境漂移。"""
    import sys
    _clean_env(monkeypatch)
    monkeypatch.setattr(sys, "stdout", _Tty())
    assert cli._resolve_panel(_ns()) == ("none", 0.0)


def test_panel_flag_without_value_is_resident():
    """`--panel` 不带值 = 常驻等人点 Stop（唯一的无限等入口）。"""
    assert cli._resolve_panel(_ns(panel=cli._PANEL_INFINITE)) == ("auto", None)


def test_panel_flag_with_seconds():
    assert cli._resolve_panel(_ns(panel=120)) == ("auto", 120.0)


def test_panel_zero_means_off():
    assert cli._resolve_panel(_ns(panel=0)) == ("none", 0.0)


def test_default_path_says_nothing_about_panel(capsys):
    """默认路径不许刷任何面板字样。

    那是每次调用的噪声；更糟的是「面板未保留」会被读成「哪一步出了问题」。
    """
    cli._note_panel(_ns(), "none", 0.0)
    err = capsys.readouterr().err
    assert "面板" not in err, f"默认路径不该提面板：{err!r}"


def test_panel_enabled_only_when_explicitly_asked():
    """面板开关的唯一判据：显式要求才算开。"""
    assert not PipelineRunner._panel_enabled("none", 0.0)
    assert not PipelineRunner._panel_enabled("", 0)
    assert PipelineRunner._panel_enabled("auto", 0.0)
    assert PipelineRunner._panel_enabled("none", 120)
    assert PipelineRunner._panel_enabled("none", None)


def test_elapsed_desc_separates_panel_wait():
    """流水线耗时与「人什么时候点 Stop」不能混成一个数字。"""
    from firmforge.core.pipeline_runner import PipelineResult

    r = PipelineResult(total_elapsed_ms=44468.0, panel_wait_ms=400000.0)
    text = cli._elapsed_desc(r)
    assert "44468ms" in text
    assert "400.0s" in text and "不计入" in text

    r2 = PipelineResult(total_elapsed_ms=44468.0, panel_wait_ms=0.0)
    assert cli._elapsed_desc(r2) == "44468ms"


# ---------------------------------------------------------------------------
# 结构性护栏：默认值 + 核心层折叠
#
# ff 的主要调用方是 Agent / CI / MCP，它们没有「人坐在面板前点 Stop」这件事。
# 危险的值（无限等）绝不能是默认值，也不能只靠「每个调用方都记得传 0」——
# CLI / json-mode / mcp_server 三条路各手写过一遍 0，其中两条漏过一次。
# ---------------------------------------------------------------------------


def test_run_full_defaults_mean_no_panel_at_all():
    """核心层默认必须是「完全无面板」：不开窗、不等待。

    只把 panel_wait 改成 0 还不够 —— panel_open 若仍是 "auto"，S5 依然会尝试
    开浏览器。默认值要一起关，否则「默认不涉及面板」只是半句话。
    """
    import inspect

    sig = inspect.signature(PipelineRunner.run_full)
    assert sig.parameters["panel_wait"].default == 0.0, \
        "panel_wait 的默认值只能是 0（返回），不能是 None（无限等）"
    assert sig.parameters["panel_open"].default == "none", \
        "panel_open 的默认值必须是 none，否则默认路径仍会开浏览器"


def test_clamp_turns_infinite_wait_into_zero_off_terminal(monkeypatch):
    import sys

    _clean_env(monkeypatch)
    monkeypatch.setattr(sys, "stdout", _Pipe())
    assert PipelineRunner._clamp_panel_wait(None) == 0.0, \
        "非交互终端上宁可没有面板，也不能让工具调用永不返回"


def test_clamp_keeps_infinite_wait_on_a_terminal(monkeypatch):
    import sys

    _clean_env(monkeypatch)
    monkeypatch.setattr(sys, "stdout", _Tty())
    assert PipelineRunner._clamp_panel_wait(None) is None


def test_clamp_leaves_explicit_values_alone(monkeypatch):
    import sys

    _clean_env(monkeypatch)
    monkeypatch.setattr(sys, "stdout", _Pipe())
    assert PipelineRunner._clamp_panel_wait(0.0) == 0.0
    assert PipelineRunner._clamp_panel_wait(120) == 120


def test_run_returns_even_if_a_caller_forgets_panel_wait(stub_stages, tmp_path,
                                                         monkeypatch):
    """不带任何面板参数调用 `run_full` 也必须返回 —— 模拟「将来的第四个调用方」。"""
    import sys
    import threading
    import time as _t

    _clean_env(monkeypatch)
    monkeypatch.setattr(sys, "stdout", _Pipe())

    app = tmp_path / "app"
    app.mkdir()
    (app / "main.c").write_text("int main(void){return 0;}", encoding="utf-8")

    # 假的「采集线程」：像真实采集那样每 100 ms 轮询 stop 文件。
    # 它**必须**响应 stop —— 真实线程不响应就是串口一直被占着，下一次烧录
    # 会以「1 秒内走完全部波特率、bytes_written=0」的假失败出现。
    stop_flag = tmp_path / "stop.flag"

    def fake_collector():
        for _ in range(30):                # 3 秒上限
            if stop_flag.exists():
                return
            _t.sleep(0.1)

    alive = threading.Thread(target=fake_collector, daemon=True)
    alive.start()

    orig_verify = PipelineRunner._stage_verify

    def verify_with_collector(self, board_id, expected="", **kw):   # noqa: ANN001
        self._collector_alive = alive
        self._collector_stop_path = str(stop_flag)
        return orig_verify(self, board_id, expected, **kw)

    monkeypatch.setattr(PipelineRunner, "_stage_verify", verify_with_collector)

    t0 = _t.time()
    result = PipelineRunner(workspace=tmp_path).run_full(
        source_dir=str(app), board_id="gc_h743")          # 关键：不传面板参数
    spent = _t.time() - t0

    assert result.stages, "流水线没有产出阶段结果"
    assert spent < 2.0, f"等了 {spent:.1f}s —— 默认值又变成无限等了"
    assert result.panel_wait_ms < 2000, \
        f"panel_wait_ms={result.panel_wait_ms:.0f}，说明等待被算进了面板时间"
    assert not alive.is_alive(), \
        "run_full 返回时采集线程还活着 —— 串口没释放，下一次烧录会假失败"
    assert not stop_flag.exists(), \
        "停止文件没清掉，下一次运行进来第一轮就会被赶走（S5 永远 0 字节）"
