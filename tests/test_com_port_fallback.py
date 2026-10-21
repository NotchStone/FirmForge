"""串口打开策略：Windows 默认不回落到 pySerial。

背景：Win11 + CH340 上 pySerial 会撞驱动兼容问题（errno 31 / stale 状态），
而 ff 的主路径是 Win32Serial（直连 Win32 API），早就绕开了。
回落分支留着只会在失败路径上重复踩坑，还把 Win32 的真实原因盖掉。

但板卡的 USB 桥不止一种（CH340 / CH340N / ATmega16U2 / FT232），
所以保留 FF_PYSERIAL_FALLBACK=1 作为逃生口；非 Windows 默认允许回落。
"""

from __future__ import annotations

import sys

import pytest

from firmforge.providers import com_port as cp
from firmforge.providers.com_port import ComPort, ComPortError, pyserial_fallback_allowed

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows 策略测试")


class _BoomWin32:
    def __init__(self, *a, **kw):
        raise OSError("CreateFile failed, err 31")


class _FakeSerial:
    opened: list[tuple] = []

    def __init__(self, **kw):
        _FakeSerial.opened.append(tuple(sorted(kw.items())))
        self.kw = kw

    def close(self):
        pass


@pytest.fixture()
def win32_fails(monkeypatch):
    import firmforge.providers.win32serial as ws
    monkeypatch.setattr(ws, "Win32Serial", _BoomWin32)
    _FakeSerial.opened.clear()
    import serial
    monkeypatch.setattr(serial, "Serial", _FakeSerial)
    return _FakeSerial


def test_windows_default_does_not_fall_back(monkeypatch, win32_fails):
    monkeypatch.delenv("FF_PYSERIAL_FALLBACK", raising=False)
    with pytest.raises(ComPortError) as ei:
        with ComPort("COM99", 115200):
            pass
    assert "FF_PYSERIAL_FALLBACK" in str(ei.value)   # 报错里给出逃生口
    assert win32_fails.opened == []                  # pySerial 一次都没被调用


def test_env_opt_in_restores_fallback(monkeypatch, win32_fails):
    monkeypatch.setenv("FF_PYSERIAL_FALLBACK", "1")
    with ComPort("COM99", 115200) as ser:
        assert isinstance(ser, _FakeSerial)
    assert len(win32_fails.opened) == 1


def test_env_zero_keeps_strict(monkeypatch, win32_fails):
    monkeypatch.setenv("FF_PYSERIAL_FALLBACK", "0")
    with pytest.raises(ComPortError):
        with ComPort("COM99", 115200):
            pass


def test_parity_translated_for_pyserial(monkeypatch, win32_fails):
    """pySerial 不认 \"None\"，回落时必须转成 \"N\"（历史 bug：抛 Not a valid parity）。"""
    monkeypatch.setenv("FF_PYSERIAL_FALLBACK", "1")
    with ComPort("COM99", 9600, parity="None"):
        pass
    kw = dict(win32_fails.opened[-1])
    assert kw["parity"] == "N"


@pytest.mark.parametrize("env,expected", [(None, False), ("1", True), ("0", False), ("true", True)])
def test_policy_matrix(monkeypatch, env, expected):
    if env is None:
        monkeypatch.delenv("FF_PYSERIAL_FALLBACK", raising=False)
    else:
        monkeypatch.setenv("FF_PYSERIAL_FALLBACK", env)
    assert pyserial_fallback_allowed() is expected
