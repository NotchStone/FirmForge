"""面板呈现策略：谁来开窗、等多久。

分工（2026-10-21 定）：
- ff 负责**提供地址并打印**，永远不假设自己有 GUI；
- 用哪个容器呈现（系统浏览器 / IDE 内嵌 / 不看）归调用方；
- auto 只在"确实有人在终端里看着"时才开窗，判据全是现成事实，不猜。
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


def test_cli_defaults():
    """默认：auto + 无限等（人工点 Stop / 关窗）。"""
    from firmforge.adapters.cli import setup_argument_parser

    args = setup_argument_parser().parse_args(
        ["run", "arduino_mega", "--app", "x"])
    assert args.open_panel == "auto"
    assert args.panel_wait is None


def test_cli_accepts_automation_values():
    from firmforge.adapters.cli import setup_argument_parser

    args = setup_argument_parser().parse_args(
        ["run", "arduino_mega", "--app", "x", "--open-panel", "none", "--panel-wait", "0"])
    assert args.open_panel == "none"
    assert args.panel_wait == 0.0
