"""Shared serial port utilities — Win32Serial primary, pySerial fallback.

ComPort: context manager using Win32 API (CreateFile/SetCommState/ReadFile).
com_port_clean_close: baud-toggle reset to heal CH340 driver lock state.

Win32Serial mirrors STC-ISP behavior — no CH340 compatibility issues.
pySerial retained as fallback for non-Windows or exotic hardware.

Used by: board_detector, pipeline_runner, all platform flash providers, collector.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

logger = logging.getLogger(__name__)

# Win32Serial 用 "None"/"Odd"/"Even"，pySerial 只认 "N"/"O"/"E"。
# 直接把 "None" 丢给 pySerial 会抛 ValueError: Not a valid parity —— 而这个
# ValueError 发生在 fallback 里，会把 Win32Serial 真正的失败原因整个盖掉，
# 于是所有串口故障都显示成「Not a valid parity」，查错方向被带偏。
_PARITY_TO_PYSERIAL = {
    "none": "N", "n": "N", "": "N",
    "odd": "O", "o": "O",
    "even": "E", "e": "E",
}


def _pyserial_parity(parity: Any) -> str:
    return _PARITY_TO_PYSERIAL.get(str(parity).strip().lower(), "N")


def pyserial_fallback_allowed() -> bool:
    """Windows 上默认**不**回落到 pySerial。

    理由：Win32Serial 与 pySerial 底层都是 CreateFile + SetCommState，能开的都能开，
    回落的收益接近零；而回落在 Win11 + CH340 上撞的正是那个坑（stale 驱动状态 /
    errno 31），失败路径会重复踩、还会把 Win32 的真实原因盖掉。

    但不同板卡的 USB 桥不一定一样（CH340 / CH340N / ATmega16U2 / FT232），
    所以留一个显式逃生口：设 FF_PYSERIAL_FALLBACK=1 即恢复回落。非 Windows 默认允许。
    """
    if sys.platform != "win32":
        return True
    return os.environ.get("FF_PYSERIAL_FALLBACK", "").strip().lower() not in ("", "0", "false", "no")


class ComPortError(Exception):
    """两条打开路径都失败。消息里同时保留 Win32Serial 与 pySerial 的原因。"""


def com_port_clean_close(port: str) -> None:
    """Reset CH340 driver via Win32 baud toggle (1200→9600)."""
    from firmforge.providers.win32serial import Win32Serial
    try:
        with Win32Serial(port, 1200, timeout=0.1):
            pass
    except Exception:
        pass
    try:
        with Win32Serial(port, 9600, timeout=0.1):
            pass
    except Exception:
        pass


class ComPort:
    """Win32Serial-primary context manager.

    Opens COM port via Win32 API — same behavior as STC-ISP.
    Falls back to pySerial for exotic hardware or non-Windows.

    Usage:
        with ComPort("COM5", 115200, timeout=0.3) as ser:
            data = ser.read(512)
    """

    def __init__(self, port: str, baud: int, timeout: float = 1.0,
                 dsrdtr: bool = True, parity: str = "None"):
        self._port = port
        self._baud = baud
        self._timeout = timeout
        self._dsrdtr = dsrdtr
        self._parity = parity
        self._ser: Any = None

    def __enter__(self):
        # 1. Win32Serial — CH340-safe, STC-ISP compatible
        win32_error: Exception | None = None
        try:
            from firmforge.providers.win32serial import Win32Serial
            self._ser = Win32Serial(self._port, self._baud, timeout=self._timeout,
                                    parity=self._parity)
            self._ser.open()
            return self._ser
        except Exception as e:
            # 记下真实原因再决定要不要回落，别再让它被 pySerial 的参数错误顶掉
            win32_error = e
            logger.debug("Win32Serial open %s failed (%s)", self._port, e)
            if not pyserial_fallback_allowed():
                raise ComPortError(
                    f"cannot open {self._port} @ {self._baud}: Win32Serial={e}. "
                    f"Windows 上不再自动回落 pySerial（那是 CH340 那条坑）；"
                    f"确需回落请设 FF_PYSERIAL_FALLBACK=1"
                ) from e

        # 2. pySerial fallback for exotic hardware
        import serial as pyserial
        try:
            self._ser = pyserial.Serial(port=self._port, baudrate=self._baud,
                                        timeout=self._timeout, dsrdtr=self._dsrdtr,
                                        parity=_pyserial_parity(self._parity))
        except Exception as e:
            raise ComPortError(
                f"cannot open {self._port} @ {self._baud}: "
                f"Win32Serial={win32_error or 'n/a'}; pySerial={e}"
            ) from (win32_error or e)
        return self._ser

    def __exit__(self, *args):
        if self._ser:
            try:
                self._ser.close()
            except Exception:
                pass

    @property
    def ser(self):
        """The underlying serial object (Win32Serial or pySerial)."""
        return self._ser
