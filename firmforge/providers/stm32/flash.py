"""STM32 FlashProvider —— OpenOCD + CMSIS-DAP（DAPLink）烧录。

与 AVR 路线最容易被搞混的一点
------------------------------
**STM32 的"端口"与烧录无关。** AVR 用 avrdude 走 UART/ISP，烧录口就是 COM 口；
STM32 走 SWD（PA13/PA14），走的是调试探针，不是串口。板载 CH340N 那条串口
**只用于 S5 回读**。

所以 `detect_port()` 在这里的语义被收窄为「S5 回读用的串口」，烧录完全不依赖
它的返回值 —— 串口没插也能烧，烧完插上再看输出。

OpenOCD 的退出码不可信
----------------------
OpenOCD 有几条路径会**打印失败信息但返回 0**（尤其是目标没响应时
`** Programming Failed **`）。所以判定成败同时看退出码与输出标记，
不能只看 `returncode`。
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from firmforge.providers.base import FlashProvider, FlashResult
from firmforge.providers.com_port import com_port_clean_close  # noqa: F401  (接口对齐)
from firmforge.providers.stm32.toolchain import Stm32Toolchain, resolve_toolchain

logger = logging.getLogger(__name__)

#: 输出里出现这些 = 失败（即使退出码为 0）
_FAILURE_MARKERS = (
    "** Programming Failed **",
    "** Verify Failed **",
    "** Unable to reset target **",
    "Error: ",
    "in procedure '",
)

#: 输出里出现这些 = 成功证据
_OK_MARKERS = ("** Programming Finished **", "** Verified OK **", "** Resetting **")

_BYTES_RE = re.compile(r"(\d+)\s+bytes\s+(?:written|from file|downloaded)")


class Stm32FlashProvider(FlashProvider):
    """STM32H7 programmer adapter (OpenOCD / CMSIS-DAP)."""

    def __init__(self, board_config: dict[str, Any]) -> None:
        super().__init__(board_config)
        self._toolchain: Stm32Toolchain = resolve_toolchain()
        self._flash_cfg: dict[str, Any] = board_config.get("flash", {}) or {}
        self._serial_cfg: dict[str, Any] = board_config.get("serial", {}) or {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect_port(self) -> str | None:
        """找 S5 回读用的串口（板载 CH340N）。

        **不参与烧录判定**。找不到就返回 None，S5 会记为「无串口」并放行
        （S5 永不阻断，见规划 §管道）。

        匹配策略刻意**不回退到任意串口**：GC-H743 的板载桥是 CH340N，
        `board.yaml::serial.port_hint` 就是声明。若退而取「第一个串口」，
        在一台有主板 COM1 的机器上会拿到 COM1 并去那里读 —— 读到的是
        空/垃圾数据，而 S5 不阻断，于是错误被静默吸收。
        **宁可返回 None 让 S5 明确说"没有回读"，也不要猜错。**
        """
        # 显式声明优先：board.yaml 写了 serial.port 就直接用，绕开"多个 CH340 分不清"。
        explicit = str(self._serial_cfg.get("port", "")).strip()
        if explicit:
            logger.info("S5 回读串口（board.yaml 指定）: %s", explicit)
            return explicit

        try:
            from firmforge.providers.win32ports import list_ports
            ports = list_ports()
        except Exception as e:
            logger.warning("串口枚举失败，检测跳过：%s", e)
            return None

        if not ports:
            return None

        hint = str(self._serial_cfg.get("port_hint", "")).strip().lower()
        keywords = ([hint] if hint else
                    ["ch340", "cp210", "ft232", "usb-serial", "usb serial"])

        matched = [p for p in ports
                   if any(kw in (p.description or "").lower()
                          or kw in (p.manufacturer or "").lower()
                          for kw in keywords)]
        if not matched:
            logger.warning(
                "没有串口匹配 %s；候选：%s。S5 将记为无回读。",
                hint or keywords,
                ", ".join(f"{p.device}({p.description})" for p in ports))
            return None

        # 多个候选一律不猜。CH340 是最常见的克隆桥：STM32 板的 CH340N 与
        # Arduino 的 CH340 在描述里一模一样、VID/PID 也相同（1A86:7523），
        # 取第一个就可能把 Arduino 的输出当成 STM32 的回读记下来。
        if len(matched) > 1:
            logger.warning(
                "多个串口匹配 %s：%s。**不猜**——S5 记为无回读；"
                "请拔掉无关板卡，或在 board.yaml 里用 serial.port 指定端口。",
                hint or keywords,
                ", ".join(f"{p.device}({p.description})" for p in matched))
            return None

        chosen = matched[0]
        logger.info("S5 回读串口: %s (%s)", chosen.device, chosen.description)
        return chosen.device

    def flash(self, firmware_path: str) -> FlashResult:
        return self._run_openocd("flash", firmware_path)

    def verify(self, firmware_path: str) -> FlashResult:
        return self._run_openocd("verify", firmware_path)

    def get_programmer_version(self) -> str:
        from firmforge.providers.stm32.toolchain import version_of
        return version_of(self._toolchain.openocd)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _preflight(self, firmware_path: str) -> str:
        if not firmware_path or not Path(firmware_path).is_file():
            return f"Firmware not found: {firmware_path}"
        problems = self._toolchain.problems()
        if problems:
            return "STM32 工具链不完整：\n  - " + "\n  - ".join(problems)
        return ""

    def _openocd_command(self, operation: str, firmware_path: str) -> list[str]:
        """拼 OpenOCD 命令行。cfg 路径与速度全部来自 board.yaml。

        参数顺序有讲究：`transport select` 与 `adapter speed` 必须排在
        `-f target/*.cfg` **之前** —— target cfg 会自己 auto-select transport
        并就此打上 DEPRECATED 警告；先选则警告消失，且行为与显式声明一致。
        """
        cfg = self._flash_cfg
        cmd = [
            self._toolchain.openocd,
            "-s", str(self._toolchain.openocd_scripts),
            "-f", str(cfg.get("interface_cfg", "interface/cmsis-dap.cfg")),
        ]
        transport = cfg.get("transport")
        if transport:
            cmd += ["-c", f"transport select {transport}"]
        speed = cfg.get("speed_khz")
        if speed:
            cmd += ["-c", f"adapter speed {speed}"]
        cmd += ["-f", str(cfg.get("target_cfg", "target/stm32h7x.cfg"))]

        # 路径含空格时必须自己加引号 —— OpenOCD 的 -c 是**它自己的**命令解析器，
        # 不走 shell，所以花括号是它认的引号写法。
        fw = "{" + str(Path(firmware_path).resolve()) + "}"
        verify = "verify " if cfg.get("verify", True) else ""
        reset = "reset " if cfg.get("reset_after", True) else ""

        if operation == "flash":
            cmd += ["-c", f"program {fw} {verify}{reset}exit"]
        else:
            cmd += ["-c", "init", "-c", "reset halt",
                    "-c", f"verify_image {fw}",
                    "-c", "reset run", "-c", "shutdown"]
        return cmd

    def _run_openocd(self, operation: str, firmware_path: str) -> FlashResult:
        start = time.time()
        gate = self._preflight(firmware_path)
        if gate:
            return FlashResult(success=False, stderr=gate, elapsed_ms=0.0)

        cmd = self._openocd_command(operation, firmware_path)
        logger.info("OpenOCD %s: %s", operation, " ".join(cmd))
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        except subprocess.TimeoutExpired:
            return FlashResult(
                success=False, elapsed_ms=(time.time() - start) * 1000,
                stderr="OpenOCD 超时（180 s）—— 探针未连接或目标未上电？",
            )
        except OSError as exc:
            return FlashResult(
                success=False, elapsed_ms=(time.time() - start) * 1000,
                stderr=f"无法启动 OpenOCD: {exc}",
            )

        out = (r.stdout or "") + (r.stderr or "")
        failures = [m for m in _FAILURE_MARKERS if m in out]
        success = r.returncode == 0 and not failures

        # 退出码 0 但一个成功标记都没有 —— 通常意味着探针根本没连上，
        # OpenOCD 静默退出了。这类"假成功"必须拦下，否则会骗过 S4。
        if success and not any(m in out for m in _OK_MARKERS):
            success = False
            failures = ["OpenOCD 未输出任何成功标记（探针未连接？）"]

        return FlashResult(
            success=success,
            bytes_written=self._bytes_written(out, firmware_path),
            stdout=r.stdout or "",
            stderr=(r.stderr or "") + ("".join(f"\n{f}" for f in failures)),
            elapsed_ms=(time.time() - start) * 1000,
        )

    @staticmethod
    def _bytes_written(output: str, firmware_path: str) -> int:
        m = _BYTES_RE.search(output)
        if m:
            return int(m.group(1))
        # 回退：Intel HEX 的实载字节数 ≈ 文本长度的一半；.bin 直接取文件大小。
        p = Path(firmware_path)
        if p.suffix.lower() == ".bin" and p.is_file():
            return p.stat().st_size
        if p.is_file():
            return max(0, p.stat().st_size // 2)
        return 0


__all__ = ["Stm32FlashProvider"]
