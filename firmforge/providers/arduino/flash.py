"""Arduino FlashProvider — avrdude programmer adapter.

Implements FlashProvider from providers/base.py.
Wraps avrdude for Arduino boards with auto-detected COM port.
"""

from __future__ import annotations
from firmforge.providers.com_port import com_port_clean_close

import logging
import os
import re
import time
from typing import Any

from firmforge.providers.base import FlashProvider, FlashResult, FlashError
from firmforge.providers.arduino.toolchain import resolve_toolchain
from firmforge.providers.textio import run_text

logger = logging.getLogger(__name__)

# 只有「端口根本没打开」这一类才算硬失败：无论 rc 是多少都按没写进去处理。
# 注意 n sync **不能**放进来：avrdude 在重试握手时会打 "n sync" 警告，
# 之后仍然可能写完并校验通过（实测 UNO：n sync 之后紧跟 2380 bytes verified）。
# 判成功要靠正向证据，不能靠"有没有出现过吓人的字符串"。
_HARD_FAIL_MARKERS = (
    "unable to open port",
    "cannot set com-state",
    "programmer is not responding",
    "initialization failed",
)


class ArduinoFlashProvider(FlashProvider):
    """Arduino AVR programmer adapter (avrdude)."""

    PROGRAMMER = "wiring"
    BAUD = 115200

    MCU_MAP: dict[str, str] = {
        "ATmega2560": "m2560",
        "ATmega328P": "m328p",
        "ATmega328":  "m328p",
        "ATmega168P": "m168p",
        "ATmega168":  "m168p",
        "ATmega88P":  "m88p",
        "ATmega48P":  "m48p",
        "ATmega32U4": "m32u4",
    }

    _BAUD_MAP: dict[str, int] = {
        "m328p": 115200,
        "m2560": 115200,
        "m32u4": 57600,
        "m168p": 19200,
        "m88p":  19200,
        "m48p":  19200,
    }

    _PART_PROGRAMMER: dict[str, str] = {
        "m2560": "wiring",
        "m328p": "arduino",
        "m32u4": "avr109",
    }

    def __init__(self, board_config: dict[str, Any]) -> None:
        super().__init__(board_config)
        self._toolchain = resolve_toolchain()
        self._mcu_part = self._resolve_mcu_part()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect_port(self) -> str | None:
        """Find the Arduino board's COM port via keyword matching.

        端口枚举走 `win32ports`（Win32 SetupAPI），**不用 pyserial**：
        后者的 list_ports 在 Win11 + CH340 上会污染驱动状态。
        Falls back to Windows registry.
        """
        try:
            from firmforge.providers.win32ports import list_ports
            ports = list_ports()
            if not ports:
                return None

            matched = []
            for p in ports:
                desc = (p.description or "").lower()
                if any(kw in desc for kw in [
                    "arduino", "ch340", "ft232", "mega",
                    "ftdi", "usb-serial", "usb serial",
                ]):
                    matched.append(p)

            if not matched:
                matched = ports

            if len(matched) > 1:
                ports_str = ", ".join(f"{p.device} ({p.description})" for p in matched)
                logger.warning("Multiple Arduino-like ports: %s. Using %s.",
                              ports_str, matched[0].device)

            logger.info("COM port: %s (%s)", matched[0].device, matched[0].description)
            return matched[0].device

        except ImportError:
            logger.warning("pyserial not available for COM detection")

        # Windows registry fallback
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DEVICEMAP\SERIALCOMM",
            )
            i = 0
            while True:
                try:
                    name, value, _ = winreg.EnumValue(key, i)
                    if "Serial" in name and "VSerial" not in name:
                        return value
                    i += 1
                except OSError:
                    break
        except Exception:
            pass

        return None

    def flash(self, firmware_path: str) -> FlashResult:
        if not os.path.exists(firmware_path):
            return FlashResult(success=False, stderr=f"Firmware not found: {firmware_path}")
        if not self._toolchain.avrdude:
            return FlashResult(
                success=False,
                stderr="AVRDUDE not found. Run `ff setup` to install toolchains.",
            )

        port = self.detect_port()
        if not port:
            return FlashResult(success=False, stderr="No COM port detected")

        return self._run_avrdude("flash", firmware_path, port)

    def verify(self, firmware_path: str) -> FlashResult:
        port = self.detect_port()
        if not port:
            return FlashResult(success=False, stderr="No COM port detected")

        return self._run_avrdude("verify", firmware_path, port)

    def get_programmer_version(self) -> str:
        try:
            proc = run_text([self._toolchain.avrdude, "--version"], timeout=5)
            return proc.stdout.splitlines()[0] if proc.stdout else "unknown"
        except Exception:
            return "unknown"

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run_avrdude(self, operation: str, firmware_path: str, port: str) -> FlashResult:
        """Execute an avrdude flash or verify operation.

        Args:
            operation: 'flash' (write) or 'verify' (read-compare)
            firmware_path: Path to .hex file
            port: COM port

        Returns:
            FlashResult with success/failure details.
        """
        # perf_counter 而非 time.time()：Windows 上 time.time() 约 15.6ms 一跳，
        # 一次被 mock 掉、实际耗时不足一跳的烧录会算出 elapsed_ms = 0.0。
        # 时长测量本来就该用单调高精度时钟。
        start = time.perf_counter()

        conf_arg = f"-C{os.path.abspath(self._toolchain.avrdude_conf)}" if self._toolchain.avrdude_conf else ""
        hex_win = os.path.abspath(firmware_path)
        programmer = self._resolve_programmer()
        op_flag = "w" if operation == "flash" else "v"

        bauds = [self._resolve_baud()] + self._get_baud_fallbacks()
        baud_attempts = 0

        for baud in bauds:
            baud_attempts += 1
            if operation == "flash":
                self._bootloader_reset(port)

            cmd = [
                self._toolchain.avrdude,
                *(["-C", self._toolchain.avrdude_conf] if self._toolchain.avrdude_conf else []),
                "-c", programmer,
                "-p", self._mcu_part,
                "-P", port,
                "-b", str(baud),
            ]
            if operation == "flash" and self._mcu_part == "m2560":
                cmd.append("-D")
            cmd.extend(["-U", f"flash:{op_flag}:{hex_win}:i"])

            logger.info("Flash %s: %s", operation, " ".join(cmd))
            proc = run_text(cmd, timeout=30)
            elapsed = (time.perf_counter() - start) * 1000
            combined = (proc.stdout or "") + (proc.stderr or "")

            if proc.returncode == 0:
                lowered = combined.lower()
                if "verification error" in lowered:
                    logger.warning("Verification error @%d: %s", baud, combined[-100:])
                    continue

                # rc==0 不等于写成功。实测（2026-10-21，Nano/CH340 端口失效）：
                # avrdude 打印 "unable to open port" 后仍然返回 0，于是「一个字节没写」
                # 被判成 PASS —— S4 是阻断点，假通过比假失败危险得多。
                # 规矩：flash 必须有写入证据；措辞对不上时用回读校验兜底，不猜。
                bytes_written = 0
                if operation == "flash":
                    # 正向证据优先：写完会打 "N bytes of flash written"，
                    # 写完顺带校验会打 "N bytes of flash verified"。
                    # 只要出现其一就算写成功——哪怕前面出现过 n sync 重试警告。
                    m_written = re.search(r'(\d+) bytes of flash written', combined, re.IGNORECASE)
                    m_verified = re.search(r'(\d+) bytes of flash verified', combined, re.IGNORECASE)
                    if m_written or m_verified:
                        bytes_written = int(m_written.group(1)) if m_written else -1
                    else:
                        marker = next((m for m in _HARD_FAIL_MARKERS if m in lowered), None)
                        if marker:
                            logger.warning("No usable target @%d (%s): %s",
                                           baud, marker, combined[-140:])
                            continue
                        # 无完成证据也无明确失败：用回读校验判定，不猜。
                        logger.info("No write evidence @%d (tail: %r); falling back to read-back verify",
                                    baud, combined[-200:])
                        if not self._run_avrdude("verify", firmware_path, port).success:
                            logger.warning("Read-back verify failed @%d", baud)
                            continue
                        bytes_written = -1  # 校验通过但字节数未知
                    com_port_clean_close(port)

                result = FlashResult(success=True, bytes_written=bytes_written,
                                   stdout=proc.stdout, stderr=proc.stderr,
                                   elapsed_ms=elapsed)
                result.baud_retries = baud_attempts - 1
                return result

            logger.warning("%s failed @%d: %s", operation.capitalize(), baud, combined[-100:])

        elapsed = (time.perf_counter() - start) * 1000
        return FlashResult(success=False, stderr=f"{operation.capitalize()} failed across all baud rates",
                           elapsed_ms=elapsed)

    def _resolve_mcu_part(self) -> str:
        chip = self._board_config.get("mcu", {}).get("chip", "")
        part = self.MCU_MAP.get(chip)
        if not part:
            raise FlashError(f"Unknown MCU chip '{chip}' — add to MCU_MAP in flash.py")
        return part

    def _resolve_baud(self) -> int:
        return self._BAUD_MAP.get(self._mcu_part, self.BAUD)

    def _get_baud_fallbacks(self) -> list[int]:
        fallbacks = [57600, 19200]
        board_bl = self._board_config.get("bootloader", {})
        if isinstance(board_bl, dict):
            if board_bl.get("baud_rate"):
                bl_baud = int(board_bl["baud_rate"])
                if bl_baud not in fallbacks:
                    fallbacks.insert(0, bl_baud)
            if board_bl.get("fallback_bauds"):
                for b in board_bl["fallback_bauds"]:
                    b = int(b)
                    if b not in fallbacks:
                        fallbacks.append(b)
        return fallbacks

    def _resolve_programmer(self) -> str:
        return self._PART_PROGRAMMER.get(self._mcu_part, "wiring")

    @staticmethod
    def _bootloader_reset(port: str) -> None:
        """Toggle DTR at 1200 baud to enter Arduino bootloader mode."""
        import time as _time
        try:
            from firmforge.providers.com_port import ComPort
            with ComPort(port, 1200, timeout=0.5):
                _time.sleep(0.2)
            _time.sleep(1.5)
            logger.debug("Bootloader reset on %s", port)
        except Exception as e:
            logger.warning("Bootloader reset on %s failed: %s", port, e)
