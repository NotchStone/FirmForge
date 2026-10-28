"""工作区解析的回归测试 —— 面板/状态/串口配置必须落在同一个地方。

被锁死的那个 bug：S5 用 `Path(__file__)` 上溯三级当工作区，那是**工具自己的
安装目录**（开发态 = 源码仓库根，装成 wheel 后 = site-packages）。后果是同一
个会话被劈成两半：state.json 写进真工作区，serial_live.html 和
serial_config.json 写进工具目录。

串口配置那一半最狠：它成了全局唯一一份，任何一个工作区的面板操作都会改掉
所有工作区的验证串口参数。实测踩过一次 —— 有人把配置写成 57600/Even，
之后每次 S5 都以错误参数开 9600 的串口，8 秒零字节判 empty，报错还说
「波特率不符/固件没在跑」，把人往硬件故障上引。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from firmforge.core.pipeline_runner import PipelineRunner
from firmforge.infrastructure import paths


class _FakeFlasher:
    def __init__(self, port: str) -> None:
        self._port = port

    def detect_port(self) -> str:
        return self._port


# ---------------------------------------------------------------------------
# resolve_workspace：显式 > 环境变量 > cwd
# ---------------------------------------------------------------------------

def test_resolve_workspace_explicit_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("FIRMFORGE_WORKSPACE", str(tmp_path / "from-env"))
    assert paths.resolve_workspace(tmp_path / "explicit") == (tmp_path / "explicit").resolve()


def test_resolve_workspace_env_used_when_explicit_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("FIRMFORGE_WORKSPACE", str(tmp_path / "from-env"))
    assert paths.resolve_workspace("") == (tmp_path / "from-env").resolve()


def test_resolve_workspace_falls_back_to_cwd(tmp_path, monkeypatch):
    monkeypatch.delenv("FIRMFORGE_WORKSPACE", raising=False)
    monkeypatch.chdir(tmp_path)
    assert paths.resolve_workspace(None) == Path.cwd()


# ---------------------------------------------------------------------------
# S5 的面板文件必须落在 workspace，不是工具安装目录
# ---------------------------------------------------------------------------

def test_verify_panel_lands_in_workspace(tmp_path, monkeypatch):
    """Verify 算出来的 html_path 必须指向 <workspace>/.ff-run/。"""
    ws = tmp_path / "proj"
    ws.mkdir()

    runner = PipelineRunner(workspace=ws)
    monkeypatch.setattr(
        "firmforge.providers.get_flash_provider",
        lambda *a, **k: _FakeFlasher("COM7"),
    )

    def _stub_collector(self, html_path, port, baud, sample_ready,
                        sample_lines, total_lines, *a, **k):
        # 真采集线程就是往 html_path 写的，这里用同一个路径留个凭证
        p = Path(html_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("stub", encoding="utf-8")
        sample_lines.extend(["L1", "L2", "L3"])
        total_lines.append(3)
        sample_ready.set()

    monkeypatch.setattr(PipelineRunner, "_collector_thread", _stub_collector)
    # 不起 HTTP 服务（端口与别的测试会打架）
    monkeypatch.setattr("firmforge.adapters.panel_service.start_panel_httpd",
                        lambda root: 0)

    stage = runner._stage_verify("arduino_mega", "")

    panel = ws / ".ff-run" / "serial_live.html"
    assert panel.exists(), f"面板没有落在工作区里：期望 {panel}"
    assert panel.read_text(encoding="utf-8") == "stub"
    assert stage.verdict == "collected"


def test_verify_reads_serial_config_from_workspace(tmp_path, monkeypatch):
    """串口配置必须是每个工作区一份，不能被邻仓改掉。"""
    ws = tmp_path / "proj"
    (ws / ".ff-run").mkdir(parents=True)
    (ws / ".ff-run" / "serial_config.json").write_text(
        '{"baud": 115200, "parity": "None"}', encoding="utf-8")

    got = PipelineRunner._load_serial_config(str(paths.runtime_dir(ws)), 9600, "None")
    assert got == (115200, "None")

    # 另一个工作区有自己的配置，互不影响
    ws2 = tmp_path / "other"
    (ws2 / ".ff-run").mkdir(parents=True)
    assert PipelineRunner._load_serial_config(
        str(paths.runtime_dir(ws2)), 9600, "None") == (9600, "None")


# ---------------------------------------------------------------------------
# MCP 入口：不能把工具安装目录当成工作区
# ---------------------------------------------------------------------------

@pytest.fixture
def spy_runner(monkeypatch):
    """把 PipelineRunner 换成只记录入参的探针，避免真跑流水线。"""
    from firmforge.core import pipeline_runner as pr

    seen: dict[str, object] = {}

    class _Spy:
        def __init__(self, **kw):
            seen.update(kw)

        def run_full(self, **kw):
            return pr.PipelineResult()

        def build(self, **kw):
            return pr.PipelineResult()

        def flash(self, **kw):
            return pr.PipelineResult()

    monkeypatch.setattr(pr, "PipelineRunner", _Spy)
    return seen


def test_do_run_uses_explicit_workspace(tmp_path, spy_runner):
    from firmforge.adapters import commands

    target = tmp_path / "proj"
    commands.do_run("arduino_mega", "app", "", str(target))
    assert Path(str(spy_runner["workspace"])) == target.resolve()


def test_do_run_uses_env_workspace(tmp_path, spy_runner, monkeypatch):
    from firmforge.adapters import commands

    target = tmp_path / "env-proj"
    monkeypatch.setenv("FIRMFORGE_WORKSPACE", str(target))
    commands.do_run("arduino_mega", "app", "", "")
    assert Path(str(spy_runner["workspace"])) == target.resolve()


def test_do_build_and_flash_honour_workspace(tmp_path, spy_runner):
    from firmforge.adapters import commands

    target = tmp_path / "proj"
    commands.do_build("arduino_mega", "app", str(target))
    assert Path(str(spy_runner["workspace"])) == target.resolve()

    commands.do_flash("arduino_mega", "firmware.hex", str(target))
    assert Path(str(spy_runner["workspace"])) == target.resolve()
