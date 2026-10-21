"""ff flash 必须按平台路由到对应的烧录提供者。

回归背景（2026-10-21，S4 首次真机验证时暴露）：
`cmd_flash` 里硬编码了 `ArduinoFlashProvider`，于是 `ff flash gc_h743` 把
STM32 板卡交给 avrdude 路线，撞在 `MCU_MAP` 上抛
`Unknown MCU chip 'STM32H743ZIT6'` —— 把「路由错了」伪装成「芯片不认识」。
pipeline_runner 一直是按 `platform` 路由的，只有 CLI 这条支路漏了。
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from firmforge.adapters import cli
from firmforge.providers.base import FlashError, FlashResult

BOARD_CFG = {
    "stm32": {"board_name": "GC-H743", "platform": "stm32", "mcu": {"chip": "STM32H743ZIT6"}},
    "arduino": {"board_name": "Mega", "platform": "arduino", "mcu": {"chip": "atmega2560"}},
}


class _FakeFlasher:
    """记录被调用的路径，并模拟「没有串口」的 SWD 路线。"""

    def __init__(self, platform: str, config: dict):
        self.platform = platform
        self.config = config
        self.flashed: list[str] = []

    def detect_port(self) -> str | None:
        return None

    def flash(self, firmware_path: str) -> FlashResult:
        self.flashed.append(firmware_path)
        return FlashResult(success=True, bytes_written=1024, elapsed_ms=42.0)


@pytest.fixture()
def patched(monkeypatch, tmp_path: Path):
    """把板卡解析与提供者工厂都换成可控桩。"""
    state = {"platform": "stm32", "flasher": None, "requested": []}

    def fake_resolve_board(self, board_id):  # noqa: ANN001
        return BOARD_CFG[state["platform"]]

    def fake_get_flash_provider(platform: str, config: dict):  # noqa: ANN001
        state["requested"].append(platform)
        state["flasher"] = _FakeFlasher(platform, config)
        return state["flasher"]

    from firmforge.core.board_detector import BoardDetector
    import firmforge.providers as providers_pkg

    monkeypatch.setattr(BoardDetector, "resolve_board", fake_resolve_board)
    monkeypatch.setattr(providers_pkg, "get_flash_provider", fake_get_flash_provider)

    hex_path = tmp_path / "firmware.hex"
    hex_path.write_text(":00000001FF\n", encoding="utf-8")
    return state, hex_path


def _args(board: str, firmware: str) -> argparse.Namespace:
    return argparse.Namespace(board=board, firmware=firmware, boards_dir=None, json=False)


def test_stm32_routes_to_stm32_provider(patched):
    """STM32 板卡必须请求 stm32 提供者，且没串口也要能烧（SWD 不依赖串口）。"""
    state, hex_path = patched
    state["platform"] = "stm32"

    assert cli.cmd_flash(_args("gc_h743", str(hex_path))) == 0
    assert state["requested"] == ["stm32"]
    assert state["flasher"].flashed == [str(hex_path)]


def test_arduino_routes_to_arduino_provider(patched):
    state, hex_path = patched
    state["platform"] = "arduino"

    # 没有串口：avrdude 路线必须硬失败，不能被 SWD 分支放过
    assert cli.cmd_flash(_args("arduino_mega", str(hex_path))) == 1
    assert state["requested"] == ["arduino"]
    assert state["flasher"].flashed == []


def test_flash_error_is_reported_without_traceback(patched, capsys):
    """可预期失败（工具链缺件等）给一行人话，不抛 traceback。"""
    state, hex_path = patched
    state["platform"] = "stm32"

    class _Failing(_FakeFlasher):
        def flash(self, firmware_path: str) -> FlashResult:
            raise FlashError("unable to find a matching CMSIS-DAP device")

    import firmforge.providers as providers_pkg

    original = providers_pkg.get_flash_provider

    def returning_failing(platform: str, config: dict):  # noqa: ANN001
        state["requested"].append(platform)
        return _Failing(platform, config)

    try:
        providers_pkg.get_flash_provider = returning_failing
        code = cli.cmd_flash(_args("gc_h743", str(hex_path)))
    finally:
        providers_pkg.get_flash_provider = original

    out = capsys.readouterr().out
    assert code == 1
    assert "CMSIS-DAP" in out
    assert "Traceback" not in out
