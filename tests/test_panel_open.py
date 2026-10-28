"""面板呈现策略：谁来开窗、等多久。**默认是关闭的。**

分工（2026-10-28 定，取代 2026-10-21 的「auto 默认开」）：
- 默认**不涉及面板**：不起 HTTP 服务、不开窗、不等待、不打地址；
- 要面板就显式 `--panel`（常驻，人点 Stop）或 `--panel 120`（留 120 秒）；
- 真开了面板时，ff 只负责**提供地址并打印**，用什么容器呈现归调用方。

为什么默认关了：ff 的主要调用方是 Agent / CI / MCP，没有「人在面板前」这回事。
默认开面板时，五个阶段 44 秒跑完还会挂 400 秒等一个不会来的 Stop ——
外部看到的现象是「命令卡死」，而且和「cppcheck 慢」长得一模一样。
"""

from __future__ import annotations

import sys

import pytest

from firmforge.core.pipeline_runner import PipelineRunner

URL = "http://127.0.0.1:9878/serial_live.html"


@pytest.fixture()
def opened(monkeypatch):
    """记录 webbrowser.open 被调用的次数，不真的开浏览器。"""
    calls: list[str] = []

    import webbrowser

    monkeypatch.setattr(webbrowser, "open", lambda u: calls.append(u) or True)
    return calls


def test_none_never_opens(opened):
    PipelineRunner._maybe_open_panel(URL, "none", None)
    assert opened == []


def test_panel_forces_open(opened):
    PipelineRunner._maybe_open_panel(URL, "panel", None)
    assert opened == [URL]


def test_zero_wait_never_opens(opened):
    """panel_wait=0 意味着看完就走，开窗没有意义。"""
    PipelineRunner._maybe_open_panel(URL, "panel", 0)
    assert opened == []


def test_auto_opens_only_when_tty(opened, monkeypatch):
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True, raising=False)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("SSH_CONNECTION", raising=False)
    PipelineRunner._maybe_open_panel(URL, "auto", None)
    assert opened == [URL]


def test_auto_silent_when_not_tty(opened, monkeypatch):
    """被 IDE / 脚本接管时 stdout 不是 tty —— 此时不该抢 UI。"""
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False, raising=False)
    PipelineRunner._maybe_open_panel(URL, "auto", None)
    assert opened == []


def test_auto_silent_in_ci(opened, monkeypatch):
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True, raising=False)
    monkeypatch.setenv("CI", "1")
    PipelineRunner._maybe_open_panel(URL, "auto", None)
    assert opened == []


def test_open_failure_does_not_raise(monkeypatch):
    """浏览器起不来不能把整条流水线拖垮。"""
    import webbrowser

    def boom(_url):
        raise RuntimeError("no GUI")

    monkeypatch.setattr(webbrowser, "open", boom)
    PipelineRunner._maybe_open_panel(URL, "panel", None)   # 不抛就算过


def test_cli_default_has_no_panel():
    """默认：`args.panel is None` → 面板功能完全关闭。

    注意断言的是「关」而不是「auto + 无限等」——旧默认正是后者，
    它让 `ff run` 在管道里永远不返回。
    """
    from firmforge.adapters import cli

    args = cli.setup_argument_parser().parse_args(
        ["run", "arduino_mega", "--app", "x"])
    assert args.panel is None
    assert cli._resolve_panel(args) == ("none", 0.0)


def test_cli_panel_flag_forms():
    """`--panel` 不带值 = 常驻；`--panel 120` = 留 120 秒。"""
    from firmforge.adapters import cli

    parser = cli.setup_argument_parser()
    resident = parser.parse_args(["run", "arduino_mega", "--app", "x", "--panel"])
    assert resident.panel == cli._PANEL_INFINITE
    assert cli._resolve_panel(resident) == ("auto", None)

    timed = parser.parse_args(["run", "arduino_mega", "--app", "x", "--panel", "120"])
    assert cli._resolve_panel(timed) == ("auto", 120.0)
