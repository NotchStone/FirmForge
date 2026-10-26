"""S5 采样窗的早退规则（零字节 1.5 s vs 有字节 8 s）。

背景：固件一个字都不输出时，等满 8 s 没有任何收益 —— 空输出的固件不会在第 7 秒
变出第一行。但"有字节、只是还没攒满 3 行"的情况必须继续等，否则只打半截内容的
固件会被误判成无输出。

所以判定依据是**收到的字节数**，不是行数。这里用假 ComPort 锁死这两条：

  1. 全程零字节 → 1.5 s 宽限后立刻交付样本（事件置位），实际耗时远小于 8 s；
  2. 有字节但没换行 → 不在 1.5 s 处早退（至少等过 3 s 仍未置位）。
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from firmforge.core.pipeline_runner import PipelineRunner


class _PortBase:
    """假 ComPort：只实现采集线程真正用到的那几个成员。"""

    def __init__(self, *args, **kwargs) -> None:
        self.ser = self

    def __enter__(self):
        return self

    def __exit__(self, *args) -> bool:
        return False

    def reset_input_buffer(self) -> None:
        pass

    def close(self) -> None:
        pass

    def write(self, data) -> int:
        return len(data)


class _SilentPort(_PortBase):
    def read(self, _n: int = 64) -> bytes:
        time.sleep(0.05)
        return b""


class _ChattyNoNewlinePort(_PortBase):
    """一直吐字节但永不带换行 —— 行数恒为 0，字节数不为 0。"""

    def read(self, _n: int = 64) -> bytes:
        time.sleep(0.05)
        return b"HB OK t=1"


def _run_collector(tmp_path: Path, monkeypatch, port_cls) -> tuple[threading.Event, list, list]:
    import firmforge.providers.com_port as com_port

    monkeypatch.setattr(com_port, "ComPort", port_cls)

    html = tmp_path / "serial_live.html"
    ready = threading.Event()
    lines: list[str] = []
    total = [0]
    runner = PipelineRunner(workspace=tmp_path)
    t = threading.Thread(
        target=runner._collector_thread,
        args=(str(html), "COM_TEST", 115200, ready, lines, total, "", "", []),
        daemon=True,
    )
    t.start()
    return ready, lines, [str(html) + ".stop"]


def test_silent_port_gives_up_in_about_1_5s(tmp_path, monkeypatch):
    ready, lines, _stop = _run_collector(tmp_path, monkeypatch, _SilentPort)

    t0 = time.time()
    assert ready.wait(timeout=6.0), "零字节时也必须交付样本（否则 S5 会挂到 8 s 超时）"
    elapsed = time.time() - t0

    assert elapsed < 3.0, f"零字节仍等了 {elapsed:.1f}s —— 早退没生效"
    assert lines == []


def test_bytes_without_newline_keeps_full_window(tmp_path, monkeypatch):
    ready, lines, stop = _run_collector(tmp_path, monkeypatch, _ChattyNoNewlinePort)

    time.sleep(3.0)
    try:
        assert not ready.is_set(), (
            "收到了字节（只是没有换行）就被提前判成无输出 —— "
            "判定依据必须是字节数，不是行数"
        )
        assert lines == []
    finally:
        Path(stop[0]).write_text("stop\n", encoding="utf-8")
