"""COM 端口枚举 —— 直连 Win32 SetupAPI，不碰 pyserial。

为什么要自己写：

Win11 + CH340 上，pyserial 的 `tools.list_ports.comports()` 会**留下 stale 驱动状态**，
之后连 avrdude 都打不开端口（`board_detector.py` 里那条注释就是为此写的，
当时的对策是"用完立刻 com_port_clean_close() 去洗"）。

ff 的串口读写已经全部走 `win32serial.py`（直连 CreateFile/SetCommState），
枚举也不该再依赖 pyserial —— 别让工具只为"列个端口名"就把那个坑重新踩一遍。

Windows 走 SetupAPI；非 Windows 才回落到 pyserial（那边没有这个问题）。
"""

from __future__ import annotations

import ctypes
import logging
import re
import sys
from ctypes import wintypes
from typing import NamedTuple

logger = logging.getLogger(__name__)


class PortInfo(NamedTuple):
    """一个 COM 端口。

    字段名刻意与 pyserial 的 ListPortInfo 对齐（device/description/vid/pid/
    serial_number/manufacturer），这样调用方换实现时不用改字段名。
    取不到的字段为 None（虚拟串口常见）。
    """

    device: str              # "COM5"
    description: str         # "USB-SERIAL CH340 (COM5)"
    vid: int | None = None
    pid: int | None = None
    serial_number: str | None = None
    manufacturer: str | None = None


# ---------------------------------------------------------------------------
# SetupAPI 绑定
# ---------------------------------------------------------------------------

_DIGCF_PRESENT = 0x02
_SPDRP_DEVICEDESC = 0x00
_SPDRP_HARDWAREID = 0x01
_SPDRP_MFG = 0x0B
_SPDRP_FRIENDLYNAME = 0x0C
_ERROR_NO_MORE_ITEMS = 259


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class _SP_DEVINFO_DATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("ClassGuid", _GUID),
        ("DevInst", wintypes.DWORD),
        ("Reserved", ctypes.c_void_p),
    ]


# {4d36e978-e325-11ce-bfc1-08002be10318} = GUID_DEVCLASS_PORTS
_GUID_DEVCLASS_PORTS = _GUID(
    0x4D36E978, 0xE325, 0x11CE,
    (ctypes.c_ubyte * 8)(0xBF, 0xC1, 0x08, 0x00, 0x2B, 0xE1, 0x03, 0x18),
)

_VID_PID_RE = re.compile(r"VID_([0-9A-Fa-f]{4})&PID_([0-9A-Fa-f]{4})")


def _setupapi():
    api = ctypes.WinDLL("setupapi", use_last_error=True)
    api.SetupDiGetClassDevsW.restype = ctypes.c_void_p
    api.SetupDiGetClassDevsW.argtypes = [
        ctypes.c_void_p, wintypes.LPCWSTR, wintypes.HWND, wintypes.DWORD,
    ]
    api.SetupDiEnumDeviceInfo.restype = wintypes.BOOL
    api.SetupDiEnumDeviceInfo.argtypes = [
        ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_SP_DEVINFO_DATA),
    ]
    api.SetupDiGetDeviceRegistryPropertyW.restype = wintypes.BOOL
    api.SetupDiGetDeviceRegistryPropertyW.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(_SP_DEVINFO_DATA), wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    api.SetupDiDestroyDeviceInfoList.restype = wintypes.BOOL
    api.SetupDiDestroyDeviceInfoList.argtypes = [ctypes.c_void_p]
    api.SetupDiGetDeviceInstanceIdW.restype = wintypes.BOOL
    api.SetupDiGetDeviceInstanceIdW.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(_SP_DEVINFO_DATA),
        wintypes.LPWSTR, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
    ]
    return api


def _prop(api, hdev, did, prop_id: int) -> str:
    """读一条设备注册表属性（字符串）。读不到返回空串。"""
    buf = ctypes.create_unicode_buffer(1024)
    needed = wintypes.DWORD(0)
    ok = api.SetupDiGetDeviceRegistryPropertyW(
        hdev, ctypes.byref(did), prop_id, None,
        buf, ctypes.sizeof(buf), ctypes.byref(needed))
    return buf.value if ok else ""


def _list_ports_win32() -> list[PortInfo]:
    api = _setupapi()
    hdev = api.SetupDiGetClassDevsW(
        ctypes.byref(_GUID_DEVCLASS_PORTS), None, None, _DIGCF_PRESENT)
    if not hdev or hdev == ctypes.c_void_p(-1).value:
        logger.debug("SetupDiGetClassDevs failed, err=%d", ctypes.get_last_error())
        return []

    out: list[PortInfo] = []
    try:
        did = _SP_DEVINFO_DATA()
        did.cbSize = ctypes.sizeof(_SP_DEVINFO_DATA)
        index = 0
        while True:
            if not api.SetupDiEnumDeviceInfo(hdev, index, ctypes.byref(did)):
                if ctypes.get_last_error() == _ERROR_NO_MORE_ITEMS:
                    break
                index += 1
                continue
            index += 1

            friendly = _prop(api, hdev, did, _SPDRP_FRIENDLYNAME)
            desc = _prop(api, hdev, did, _SPDRP_DEVICEDESC)
            hwids = _prop(api, hdev, did, _SPDRP_HARDWAREID)
            mfg = _prop(api, hdev, did, _SPDRP_MFG)

            # 端口名：优先从 FriendlyName 的 "(COMx)" 里取，取不到再看 DeviceDesc
            m = re.search(r"\((COM\d+)\)", friendly) or re.search(r"\b(COM\d+)\b", friendly)
            if not m:
                m = re.search(r"\b(COM\d+)\b", desc)
            if not m:
                continue
            device = m.group(1)

            vid = pid = None
            vm = _VID_PID_RE.search(hwids)
            if vm:
                vid, pid = int(vm.group(1), 16), int(vm.group(2), 16)

            # 序列号 = 设备实例 ID 的最后一段（USB\VID_xxxx&PID_xxxx\<serial>）
            inst = ctypes.create_unicode_buffer(512)
            serial = None
            if api.SetupDiGetDeviceInstanceIdW(hdev, ctypes.byref(did), inst,
                                               ctypes.sizeof(inst), None):
                tail = inst.value.rsplit("\\", 1)[-1] if inst.value else ""
                serial = tail or None

            out.append(PortInfo(device=device,
                                description=friendly or desc or device,
                                vid=vid, pid=pid,
                                serial_number=serial,
                                manufacturer=mfg or None))
    finally:
        api.SetupDiDestroyDeviceInfoList(hdev)
    return out


def _list_ports_pyserial() -> list[PortInfo]:
    """非 Windows 才用。Windows 上不要走这条路（会污染 CH340 驱动状态）。"""
    import serial.tools.list_ports

    return [
        PortInfo(device=p.device, description=p.description or p.device,
                 vid=p.vid, pid=p.pid)
        for p in serial.tools.list_ports.comports()
    ]


def list_ports() -> list[PortInfo]:
    """列出当前存在的 COM 端口（按端口名排序）。"""
    try:
        ports = _list_ports_win32() if sys.platform == "win32" else _list_ports_pyserial()
    except Exception as e:                     # 枚举失败不该让调用方崩
        logger.warning("COM port enumeration failed: %s", e)
        return []
    ports.sort(key=lambda p: (len(p.device), p.device))
    return ports


def com_port_names() -> list[str]:
    return [p.device for p in list_ports()]
