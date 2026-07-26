"""Shared serial port utilities — Win32Serial primary, pySerial fallback.

ComPort: context manager using Win32 API (CreateFile/SetCommState/ReadFile).
com_port_clean_close: baud-toggle reset to heal CH340 driver lock state.

Win32Serial mirrors STC-ISP behavior — no CH340 compatibility issues.
pySerial retained as fallback for non-Windows or exotic hardware.

Used by: board_detector, pipeline_runner, all platform flash providers, collector.
"""

from __future__ import annotations

from typing import Any


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
                 dsrdtr: bool = True):
        self._port = port
        self._baud = baud
        self._timeout = timeout
        self._dsrdtr = dsrdtr
        self._ser: Any = None

    def __enter__(self):
        # 1. Win32Serial — CH340-safe, STC-ISP compatible
        try:
            from firmforge.providers.win32serial import Win32Serial
            self._ser = Win32Serial(self._port, self._baud, timeout=self._timeout)
            self._ser.open()
            return self._ser
        except Exception:
            # 2. pySerial fallback for exotic hardware
            import serial as pyserial
            self._ser = pyserial.Serial(port=self._port, baudrate=self._baud,
                                        timeout=self._timeout, dsrdtr=self._dsrdtr)
            return self._ser

    def __exit__(self, *args):
        if self._ser:
            try:
                self._ser.close()
            except Exception:
                pass
