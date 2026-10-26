"""S5 采集线程必须在命令返回前释放串口（采集线程滞留的回归测试）。

`panel_wait` 为有限值（0 或 N 秒）时，`run_full` 返回即代表这次硬件操作结束。
但采集线程是 daemon 线程：不写 stop 文件它就一直持有 COM 口，于是**下一次
flash 打不开端口**——表现为 1 秒内走完所有波特率、bytes_written=0 的「假失败」。

实测症状：连续两次 `ff run`，第二次烧录必失败；手工写一个
`serial_live.html.stop` 让它退出后，同样的烧录一次就成功。

这条测试用真实 `_stage_verify`（只把采集线程本体换成「先给样本、再死等
stop 文件」的假实现），锁死三件事：
  1. run_full 返回时采集线程已经退出（串口已释放）
  2. 停止信号确实送到采集线程，且用完后不留残骸
  3. 线程正常退出时不得误报「5s 内未退出」（join() 返回 None 的坑）
"""

from __future__ import annotations

import logging
import os
import threading
import time
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
    """返回 (runner, app_dir, ctl)；ctl["collector_started"] 记录线程启动次数。"""
    app = tmp_path / "app"
    app.mkdir()
    (app / "main.c").write_text("int main(void){return 0;}\n", encoding="utf-8")
    fw = tmp_path / "firmware.hex"
    fw.write_bytes(b":00000001FF\n")

    monkeypatch.setattr(
        "firmforge.providers.get_flash_provider",
        lambda *a, **k: _FakeFlasher("COM7"),
    )
    # 不起 HTTP 服务（端口与别的测试会打架）
    monkeypatch.setattr(
        "firmforge.adapters.mcp_server._start_monitor_httpd",
        lambda root: 0,
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
    runner._stage_flash = lambda b, f: PipelineStage(stage=4, name="Flash", success=True)

    ctl = {"collector_started": 0, "saw_stop": False}

    def _fake_collector(self, html_path, port, baud, sample_ready,
                        sample_lines_out, total_lines_out, *a, **k):
        """模拟真采集线程：先交付样本，然后一直 hold 串口直到出现 stop 文件。"""
        ctl["collector_started"] += 1
        p = Path(html_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("stub", encoding="utf-8")
        sample_lines_out.extend(["OK", "OK", "OK"])
        total_lines_out.append(3)
        sample_ready.set()
        stop_path = html_path + ".stop"
        deadline = time.time() + 15
        while not os.path.exists(stop_path) and time.time() < deadline:
            time.sleep(0.02)
        ctl["saw_stop"] = os.path.exists(stop_path)

    monkeypatch.setattr(PipelineRunner, "_collector_thread", _fake_collector)
    return runner, app, ctl


def test_panel_wait_zero_releases_the_serial_port(harness):
    """panel_wait=0：命令返回时采集线程必须已退出，否则串口仍被占用。"""
    runner, app, ctl = harness

    result = runner.run_full(
        source_dir=str(app), board_id="arduino_mega", expected="OK", panel_wait=0,
    )

    assert result.overall_success is True, result
    assert ctl["collector_started"] == 1, "S5 根本没有启动采集线程"

    thread = getattr(runner, "_collector_alive", None)
    assert thread is not None
    assert not thread.is_alive(), (
        "run_full 已返回，但采集线程还活着 —— 它仍持有 COM 口，"
        "下一次 flash 会因端口被占而失败（1s 内走完所有波特率、bytes_written=0）"
    )


def test_panel_wait_zero_writes_the_stop_file(harness):
    """停止信号必须真的送到采集线程，且用完后不留残骸。

    「送到了」靠采集线程自己的观测（它看到文件才退出），不是靠文件存在；
    「不留残骸」是因为残留的 .stop 会被任何没做清理的入口当成「立刻退出」，
    表现为「固件没在跑」——这个坑本仓库已经踩过一次。
    """
    runner, app, ctl = harness

    runner.run_full(
        source_dir=str(app), board_id="arduino_mega", expected="OK", panel_wait=0,
    )

    stop_path = getattr(runner, "_collector_stop_path", "")
    assert stop_path, "_stage_verify 没有记录 stop 文件路径"
    assert ctl["saw_stop"] is True, "采集线程没看到停止信号 —— 它会一直握着串口"
    assert not Path(stop_path).exists(), (
        "run_full 返回后 .stop 文件还在：下一个入口进来第一轮就会被它赶走"
    )


def test_no_false_alarm_about_port_occupancy(harness, caplog):
    """采集线程正常退出时，不得打印「5s 内未退出」。

    `Thread.join()` 返回 None 而非 bool，写成 `if not join(...)` 会让这条
    唯一的端口占用告警每次都响，最终变成人人忽略的噪声。
    """
    runner, app, _ctl = harness

    with caplog.at_level(logging.WARNING):
        runner.run_full(
            source_dir=str(app), board_id="arduino_mega", expected="OK", panel_wait=0,
        )

    noisy = [r.getMessage() for r in caplog.records if "未退出" in r.getMessage()]
    assert not noisy, f"采集线程已正常退出，却仍报端口占用：{noisy}"


def test_open_failure_verdict_is_port_busy_not_empty(harness, monkeypatch):
    """端口压根没打开 → port_busy。

    以前这种情况会被报成 `empty`：「串口已打开（115200 bps）但 8s 内没收到
    任何字节：固件没在跑 / 波特率不符 / TX 未接到 RX」。可实际是端口被占
    （panel 常驻的采集线程还没退），固件根本没被检验过 —— 那句 error 会把人
    整个往硬件故障上引。前提缺失和结果为空必须分开报。
    """
    runner, app, ctl = harness

    def _busy_collector(self, html_path, port, baud, sample_ready, sample_lines_out,
                        total_lines_out, stages_info="", process_info="",
                        open_errors=None):
        ctl["collector_started"] += 1
        if open_errors is not None:
            open_errors.append("PermissionError: 拒绝访问。")
        sample_ready.set()  # 别让 verify 干等 8s

    monkeypatch.setattr(PipelineRunner, "_collector_thread", _busy_collector)

    result = runner.run_full(
        source_dir=str(app), board_id="arduino_mega", expected="OK", panel_wait=0,
    )

    verify = next(s for s in result.stages if s.name == "Verify")
    assert ctl["collector_started"] == 1
    assert verify.success is False
    assert verify.verdict == "port_busy", (
        f"端口没打开却被报成 {verify.verdict!r} —— 固件从未被检验，"
        "这个结论不能伪装成「打开了但没数据」"
    )
    assert "PermissionError" in verify.error
    assert verify.details.get("verdict") == "port_busy"
    assert verify.details.get("sample_count") == 0


def test_next_verify_recycles_a_leftover_collector(harness, tmp_path, caplog):
    """上一轮采集线程还活着（panel 常驻）→ 新一轮必须先叫停它，再开端口。

    不回收就直接开新线程的后果：连续 10 次打开失败，最后被报成
    「串口已打开但 8s 没收到字节」，排查被引向波特率 / 接线 / 固件。
    """
    runner, app, _ctl = harness
    ctl_result = runner.run_full(
        source_dir=str(app), board_id="arduino_mega", expected="OK", panel_wait=0,
    )
    assert ctl_result.overall_success is True, ctl_result
    assert not runner._collector_alive.is_alive()

    # 伪造「上一轮线程仍持着端口」：死等 stop 文件才退出。
    leftover_stop = tmp_path / "leftover.stop"

    def _hold_port():
        deadline = time.time() + 15
        while not leftover_stop.exists() and time.time() < deadline:
            time.sleep(0.02)

    leftover = threading.Thread(target=_hold_port, daemon=True)
    leftover.start()
    runner._collector_alive = leftover
    runner._collector_stop_path = str(leftover_stop)

    with caplog.at_level(logging.INFO):
        runner.run_full(
            source_dir=str(app), board_id="arduino_mega", expected="OK", panel_wait=0,
        )

    assert not leftover.is_alive(), (
        "新一轮 S5 没有回收上一轮采集线程 —— 端口仍被占，打开必然失败"
    )
    assert leftover_stop.exists(), "回收信号没写到上一轮的 stop 路径上"
    assert any("回收上一轮采集线程" in r.getMessage() for r in caplog.records)
