"""端口枚举必须走 Win32 SetupAPI，不能碰 pyserial。

背景（2026-10-21）：Win11 + CH340 上 pyserial 的 `tools.list_ports.comports()`
会留下 stale 驱动状态，之后连 avrdude 都打不开端口（`board_detector.py` 里
那条注释就是这么来的）。ff 的串口读写早已改用 Win32Serial 绕开，
枚举若还依赖 pyserial，等于把坑重新踩一遍——而且只为"列个端口名"。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

from firmforge.providers.win32ports import PortInfo, com_port_names, list_ports

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Win32 only")


def test_list_ports_returns_com_names():
    ports = list_ports()
    if not ports:                      # 无串口的环境不应判失败
        pytest.skip("no COM ports on this machine")
    for p in ports:
        assert isinstance(p, PortInfo)
        assert re.fullmatch(r"COM\d+", p.device), p.device
        assert p.description            # 至少有名字，便于人看


def test_com_port_names_matches_list_ports():
    assert com_port_names() == [p.device for p in list_ports()]


def test_enumeration_does_not_import_pyserial():
    """模块源码里不该出现 pyserial —— 这是防回归的硬约束。"""
    src = (Path(__file__).resolve().parents[1]
           / "firmforge" / "providers" / "win32ports.py").read_text(encoding="utf-8")
    # 只允许在非 Windows 回落分支里出现
    windows_part = src.split("def _list_ports_win32")[0]
    assert "serial.tools" not in windows_part
    assert "import serial" not in windows_part


def test_call_sites_use_win32ports():
    """四个调用点都不该再直接调 pyserial 的 comports()。"""
    root = Path(__file__).resolve().parents[1] / "firmforge"
    offenders = []
    for path in (root / "core" / "board_detector.py",
                 root / "providers" / "arduino" / "flash.py",
                 root / "providers" / "stm32" / "flash.py"):
        text = path.read_text(encoding="utf-8")
        if "serial.tools.list_ports" in text:
            offenders.append(path.name)
    assert not offenders, f"仍在用 pyserial 枚举端口: {offenders}"


def test_vid_pid_parsed_for_usb_serial():
    """USB 转串口应能拿到 vid/pid；虚拟串口拿不到也不算错。"""
    ports = [p for p in list_ports() if p.description]
    usb_like = [p for p in ports if any(k in p.description.lower()
                                        for k in ("ch340", "ft232", "cp210", "usb-serial"))]
    if not usb_like:
        pytest.skip("no USB-serial adapter attached")
    assert all(p.vid is not None and p.pid is not None for p in usb_like)
