"""Shared serial port utilities — platform-agnostic COM port layer.

ComPort: pyserial context manager with Win32Serial fallback for CH340 4.0 driver.
com_port_clean_close: safe port close that handles stale lock state.

Used by: board_detector, pipeline_runner, all platform flash providers.
"""

from __future__ import annotations

from typing import Any


def com_port_clean_close(port: str) -> None:
    """Clean close a COM port — restores CH340 driver state without DTR reset."""
    try:
        with ComPort(port, 9600, timeout=0.1, dsrdtr=False):
            pass
    except Exception:
        pass


class ComPort:
    """Auto-fallback serial port: pyserial -> Win32Serial.

    CH340 3.9/4.0 driver fails on same-baud SetCommState.
    This wraps the open with a toggle fallback transparently.

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
        import serial as pyserial
        try:
            self._ser = pyserial.Serial(port=self._port, baudrate=self._baud,
                                        timeout=self._timeout, dsrdtr=self._dsrdtr)
        except Exception:
            from firmforge.providers.win32serial import Win32Serial
            self._ser = Win32Serial(self._port, self._baud, timeout=self._timeout)
            self._ser.open()
        return self._ser

    def __exit__(self, *args):
        if self._ser:
            try:
                self._ser.close()
            except Exception:
                pass
