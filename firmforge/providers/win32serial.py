"""Win32 serial port — primary backend for CH340 reliability.

Uses direct Win32 API (CreateFile/SetCommState/ReadFile/CloseHandle).
Fully replaces pySerial for COM port operations — port enumeration included.
STC-ISP compatible behavior for all CH340 driver versions.
"""

from __future__ import annotations

import ctypes
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
OPEN_EXISTING = 3
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

CLRDTR = 6
CLRRTS = 4
PURGE_RXCLEAR = 0x0008
PURGE_TXCLEAR = 0x0004

HEAL_BAUD = 115200


class _DCB(ctypes.Structure):
    _fields_ = [
        ("DCBlength", ctypes.c_uint32),
        ("BaudRate",  ctypes.c_uint32),
        ("flags",     ctypes.c_uint32),
        ("wReserved", ctypes.c_uint16),
        ("XonLim",    ctypes.c_uint16),
        ("XoffLim",   ctypes.c_uint16),
        ("ByteSize",  ctypes.c_byte),
        ("Parity",    ctypes.c_byte),
        ("StopBits",  ctypes.c_byte),
        ("XonChar",   ctypes.c_char),
        ("XoffChar",  ctypes.c_char),
        ("ErrorChar", ctypes.c_char),
        ("EofChar",   ctypes.c_char),
        ("EvtChar",   ctypes.c_char),
        ("wReserved1", ctypes.c_uint16),
    ]


class _COMMTIMEOUTS(ctypes.Structure):
    _fields_ = [
        ("ReadIntervalTimeout",          ctypes.c_uint32),
        ("ReadTotalTimeoutMultiplier",   ctypes.c_uint32),
        ("ReadTotalTimeoutConstant",     ctypes.c_uint32),
        ("WriteTotalTimeoutMultiplier",  ctypes.c_uint32),
        ("WriteTotalTimeoutConstant",    ctypes.c_uint32),
    ]


_k = ctypes.WinDLL("kernel32", use_last_error=True)
_k.CreateFileW.restype = ctypes.c_void_p
_k.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
_k.CloseHandle.argtypes = [ctypes.c_void_p]
_k.GetCommState.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
_k.SetCommState.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
_k.SetCommTimeouts.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
_k.SetupComm.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32]
_k.PurgeComm.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
_k.EscapeCommFunction.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
_k.GetLastError.restype = ctypes.c_uint32
_k.ReadFile.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32), ctypes.c_void_p]
_k.WriteFile.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32), ctypes.c_void_p]


_PARITY_MAP = {"None": 0, "Odd": 1, "Even": 2}

def _build_dcb(baud, parity="None"):
    d = _DCB()
    d.DCBlength = ctypes.sizeof(_DCB)
    d.BaudRate = baud
    d.flags = 0x00000001 | (1 << 4) | (1 << 12)  # fBinary, DTR enable, RTS enable
    d.ByteSize = 8
    d.Parity = _PARITY_MAP.get(str(parity), 0)
    d.StopBits = 0  # ONESTOPBIT
    return d


class Win32SerialError(Exception):
    pass


class Win32Serial:
    """Fallback serial port — heals CH340 4.0 same-baud SetCommState bug."""

    def __init__(self, port, baudrate=9600, timeout=1.0, parity="None"):
        if not port.startswith("\\\\.\\"):
            port = "\\\\.\\" + port
        self._port = port
        self._port_display = port.replace("\\\\.\\", "")
        self._baudrate = int(baudrate)
        self._timeout = timeout
        self._parity = parity
        self._handle = None

    @property
    def port(self):
        return self._port_display

    @property
    def baudrate(self):
        return self._baudrate

    @baudrate.setter
    def baudrate(self, value):
        value = int(value)
        if value == self._baudrate or self._handle is None:
            self._baudrate = value
            return
        cur = _DCB()
        cur.DCBlength = ctypes.sizeof(_DCB)
        if _k.GetCommState(self._handle, ctypes.byref(cur)) and cur.BaudRate == value:
            heal = HEAL_BAUD if value != HEAL_BAUD else 9600
            _k.SetCommState(self._handle, ctypes.byref(_build_dcb(heal, self._parity)))
        dcb = _build_dcb(value, self._parity)
        if not _k.SetCommState(self._handle, ctypes.byref(dcb)):
            raise Win32SerialError(f"baudrate setter: SetCommState({value}) failed, err {_k.GetLastError()}")
        self._baudrate = value

    def open(self):
        h = _k.CreateFileW(self._port, GENERIC_READ | GENERIC_WRITE, 0, None, OPEN_EXISTING, 0, None)
        if not h or h == INVALID_HANDLE_VALUE:
            raise Win32SerialError(f"CreateFile failed, err {_k.GetLastError()}")
        self._handle = h

        cur = _DCB()
        cur.DCBlength = ctypes.sizeof(_DCB)
        _k.GetCommState(h, ctypes.byref(cur))

        if cur.BaudRate == self._baudrate:
            heal = HEAL_BAUD if self._baudrate != HEAL_BAUD else 9600
            _k.SetCommState(h, ctypes.byref(_build_dcb(heal, self._parity)))
            logger.debug("Win32Serial open: healed same-baud via toggle %d", heal)

        dcb = _build_dcb(self._baudrate, self._parity)
        if not _k.SetCommState(h, ctypes.byref(dcb)):
            raise Win32SerialError(f"SetCommState({self._baudrate}) failed, err {_k.GetLastError()}")

        to = _COMMTIMEOUTS()
        if self._timeout <= 0:
            to.ReadIntervalTimeout = 0xFFFFFFFF
        else:
            to.ReadIntervalTimeout = 0xFFFFFFFF
            to.ReadTotalTimeoutMultiplier = 0xFFFFFFFF
            to.ReadTotalTimeoutConstant = int(self._timeout * 1000)
        _k.SetCommTimeouts(h, ctypes.byref(to))
        _k.SetupComm(h, 4096, 4096)
        _k.PurgeComm(h, PURGE_RXCLEAR | PURGE_TXCLEAR)
        return self

    def read(self, size=1):
        buf = (ctypes.c_ubyte * size)()
        nread = ctypes.c_uint32(0)
        if not _k.ReadFile(self._handle, buf, size, ctypes.byref(nread), None):
            raise Win32SerialError("ReadFile failed")
        return bytes(buf[:nread.value])

    def readline(self):
        line = bytearray()
        while True:
            b = self.read(1)
            if not b:
                break
            line += b
            if b == b"\n":
                break
        return bytes(line)

    def write(self, data):
        data = bytes(data)
        n = len(data)
        if n == 0:
            return 0
        buf = (ctypes.c_ubyte * n).from_buffer_copy(data)
        nw = ctypes.c_uint32(0)
        if not _k.WriteFile(self._handle, buf, n, ctypes.byref(nw), None):
            raise Win32SerialError("WriteFile failed")
        return nw.value

    def close(self):
        if self._handle is None:
            return
        try:
            _k.PurgeComm(self._handle, PURGE_RXCLEAR | PURGE_TXCLEAR)
        except Exception:
            pass
        _k.CloseHandle(self._handle)
        self._handle = None

    def reset_input_buffer(self):
        """Clear pending input (PurgeComm RXCLEAR)."""
        if self._handle is not None:
            _k.PurgeComm(self._handle, PURGE_RXCLEAR)

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *args):
        self.close()
