"""run_full 的「判定与落盘先后顺序」回归测试。

纯逻辑测试（test_pipeline_state.py）永远抓不到这两个 bug —— 它们每次都新建
PipelineState 从磁盘重读，而 bug 出在**同一次调用里**：先把新指纹写进去，
再拿它跟自己做跳过判定。所以这里必须驱动真实的 run_full，只把碰硬件的
三个阶段（Detect / Flash / Verify）换掉，指纹计算、跳过判定、落盘顺序
全部走真代码。

两条被锁死的行为：
  1. 源码变了 → S4 必须重新烧录（曾经：指纹自比较恒真，第一次烧成功后就再也不烧）
  2. S5 失败 → 下一次调用必须重新验证，不能因为指纹相同就报 [skipped] 通过
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from firmforge.core.pipeline_runner import PipelineRunner, PipelineStage


class _FakeFlasher:
    """只提供 detect_port()，用来控制「当前插在哪个口」。"""

    def __init__(self, port: str) -> None:
        self._port = port

    def detect_port(self) -> str:
        return self._port


@pytest.fixture
def harness(tmp_path, monkeypatch):
    """返回 (runner, app_dir, fw_path, ctl)。

    ctl 里可以改：
      ctl["port"]      当前 COM 口（影响指纹）
      ctl["verify"]    "ok" / "empty"
      ctl["flash_calls"] / ctl["verify_calls"]  计数
    """
    app = tmp_path / "app"
    app.mkdir()
    (app / "main.c").write_text("int main(void){return 0;}\n", encoding="utf-8")
    fw = tmp_path / "firmware.hex"
    fw.write_bytes(b":00000001FF\n")

    ctl = {"port": "COM7", "verify": "ok", "flash_calls": 0, "verify_calls": 0}

    # run_full 里是函数内 import，patch 模块属性即可生效
    monkeypatch.setattr(
        "firmforge.providers.get_flash_provider",
        lambda *a, **k: _FakeFlasher(ctl["port"]),
    )

    runner = PipelineRunner(workspace=tmp_path)
    runner._stage_detect = lambda b: PipelineStage(
        stage=1, name="Detect", success=True,
        details={"board_id": "arduino_mega", "config": {"platform": "arduino"}},
    )
    runner._stage_review = lambda b, s, c: PipelineStage(stage=2, name="Review", success=True)
    runner._stage_build = lambda b, s: PipelineStage(
        stage=3, name="Build", success=True, details={"firmware_path": str(fw)},
    )

    def _flash(b, f):
        ctl["flash_calls"] += 1
        return PipelineStage(stage=4, name="Flash", success=True)

    def _verify(b, e="", **kw):
        ctl["verify_calls"] += 1
        if ctl["verify"] == "empty":
            return PipelineStage(stage=5, name="Verify", success=False,
                                 error="8s 内没收到任何字节", verdict="empty")
        return PipelineStage(stage=5, name="Verify", success=True, verdict="verified",
                             details={"sample_lines": ["OK"]})

    runner._stage_flash = _flash
    runner._stage_verify = _verify
    return runner, app, fw, ctl


def _stage(result, name):
    return next(s for s in result.stages if s.name == name)


def test_source_change_forces_reflash(harness):
    """源码变了必须重烧 —— 这是那个「改完代码板子还在跑旧固件」的 bug。"""
    runner, app, _fw, ctl = harness

    r1 = runner.run_full(source_dir=str(app), board_id="arduino_mega", expected="OK")
    assert ctl["flash_calls"] == 1
    assert _stage(r1, "Flash").details.get("skipped") is None

    # 动一个字节
    (app / "main.c").write_text("int main(void){return 1;}\n", encoding="utf-8")

    r2 = runner.run_full(source_dir=str(app), board_id="arduino_mega", expected="OK")
    assert ctl["flash_calls"] == 2, "源码变了却跳过了烧录"
    assert not _stage(r2, "Flash").details.get("skipped")


def test_unchanged_inputs_still_skip_flash(harness):
    """输入没变时该跳还是要跳，别把增量缓存一并修没了。"""
    runner, app, _fw, ctl = harness
    runner.run_full(source_dir=str(app), board_id="arduino_mega", expected="OK")
    r2 = runner.run_full(source_dir=str(app), board_id="arduino_mega", expected="OK")
    assert ctl["flash_calls"] == 1
    assert _stage(r2, "Flash").details.get("skipped") is True


def test_port_change_forces_reflash_even_if_build_skipped(harness):
    """源码没变（Build 跳过）但换了 COM 口 → 新口上的板子还是旧固件，必须重烧。"""
    runner, app, _fw, ctl = harness
    runner.run_full(source_dir=str(app), board_id="arduino_mega", expected="OK")

    ctl["port"] = "COM9"
    r2 = runner.run_full(source_dir=str(app), board_id="arduino_mega", expected="OK")
    assert _stage(r2, "Build").details.get("skipped") is True
    assert ctl["flash_calls"] == 2, "换口了还复用旧指纹跳过烧录"


def test_verify_failure_is_not_cached_as_pass(harness):
    """S5 失败后，同输入的第二次调用必须重试验证，而不是报 [skipped] 通过。

    这是最阴的一条：失败不报错、不告警，只是被写进状态文件，下一次
    调用直接跳过 S5 并给出 overall_success=True。
    """
    runner, app, _fw, ctl = harness
    ctl["verify"] = "empty"

    r1 = runner.run_full(source_dir=str(app), board_id="arduino_mega")
    assert r1.overall_success is False
    assert _stage(r1, "Verify").verdict == "empty"

    state = json.loads((Path(runner._workspace) / ".ff-run" / "state.json")
                       .read_text(encoding="utf-8"))
    assert state["stages"]["test"]["status"] == "failed"

    r2 = runner.run_full(source_dir=str(app), board_id="arduino_mega")
    assert ctl["verify_calls"] == 2, "上一次验证失败，这次却跳过了 S5"
    assert not _stage(r2, "Verify").details.get("skipped")
    assert r2.overall_success is False, "验证失败被粘成了下一轮的通过"


def test_verify_success_is_cacheable(harness):
    """验证成功过一次，同输入再调可以跳过（增量的意义）。"""
    runner, app, _fw, ctl = harness
    runner.run_full(source_dir=str(app), board_id="arduino_mega")
    r2 = runner.run_full(source_dir=str(app), board_id="arduino_mega")
    assert ctl["verify_calls"] == 1
    assert _stage(r2, "Verify").details.get("skipped") is True
    assert r2.overall_success is True
