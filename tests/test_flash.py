"""Integration tests for Arduino FlashProvider — mock avrdude calls.

Tests flash.py behavior without needing real hardware or avrdude.
Uses unittest.mock to verify:
- Flash command construction (programmer, MCU, port, baud, flags)
- MCU map completeness
- Verify operation
- Error handling for unknown chips
- FlashError propagation
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from firmforge.providers.base import FlashResult, FlashError

# Patch toolchain and COM port detection before importing ArduinoFlashProvider
from firmforge.providers.arduino import toolchain as tc_module
from firmforge.providers.arduino import flash as flash_module

_FAKE_TOOLCHAIN = tc_module.ToolchainPaths(
    avr_gcc="/fake/bin/avr-gcc",
    avr_objcopy="/fake/bin/avr-objcopy",
    avrdude="/fake/bin/avrdude",
    avrdude_conf="/fake/etc/avrdude.conf",
)


def _board_config(chip: str = "ATmega328P") -> dict:
    return {
        "board_name": f"Test Board ({chip})",
        "mcu": {"chip": chip},
        "aliases": ["test_board"],
    }


@pytest.fixture
def fake_hex_path(tmp_path) -> str:
    """Create a dummy .hex file for flash tests."""
    hex_file = tmp_path / "firmware.hex"
    hex_file.write_text(":100000000C9434000C9446000C9446000C94460080\n")
    return str(hex_file)


# ---------------------------------------------------------------------------
# Toolchain + port mocking
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _patch_toolchain(monkeypatch):
    monkeypatch.setattr(tc_module, "resolve_toolchain", lambda: _FAKE_TOOLCHAIN)


def _mock_port(monkeypatch, port: str):
    monkeypatch.setattr(flash_module.ArduinoFlashProvider, "detect_port",
                        lambda self: port)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestFlashCommandConstruction:
    """Verifies avrdude command structure for different MCUs."""

    def test_m328p_flash_command(self, monkeypatch, fake_hex_path):
        """ATmega328P: should use arduino programmer, no -D flag."""
        from firmforge.providers.arduino.flash import ArduinoFlashProvider

        _mock_port(monkeypatch, "COM3")
        provider = ArduinoFlashProvider(_board_config("ATmega328P"))

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout="avrdude: 5340 bytes of flash written\n", stderr="")
            result = provider.flash(fake_hex_path)

        assert result.success is True
        cmd = mock_run.call_args[0][0]
        assert "arduino" in cmd or any("arduino" in str(a) for a in cmd)
        assert "m328p" in cmd or any("m328p" in str(a) for a in cmd)
        assert "COM3" in cmd or any("COM3" in str(a) for a in cmd)
        assert ":w:" in str(cmd)  # write operation

    def test_m2560_flash_command_with_D_flag(self, monkeypatch, fake_hex_path):
        """ATmega2560: should use wiring programmer with -D (no chip erase)."""
        from firmforge.providers.arduino.flash import ArduinoFlashProvider

        _mock_port(monkeypatch, "COM4")
        provider = ArduinoFlashProvider(_board_config("ATmega2560"))

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout="avrdude: 5340 bytes of flash written\n", stderr="")
            result = provider.flash(fake_hex_path)

        assert result.success is True
        cmd = mock_run.call_args[0][0]
        cmd_str = " ".join(str(a) for a in cmd)
        assert "-D" in cmd_str
        assert "wiring" in cmd_str
        assert "m2560" in cmd_str
        assert "115200" in cmd_str

    def test_m32u4_flash_command(self, monkeypatch, fake_hex_path):
        """ATmega32U4: should use avr109 programmer."""
        from firmforge.providers.arduino.flash import ArduinoFlashProvider

        _mock_port(monkeypatch, "COM5")
        provider = ArduinoFlashProvider(_board_config("ATmega32U4"))

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout="avrdude: 5340 bytes of flash written\n", stderr="")
            result = provider.flash(fake_hex_path)

        assert result.success is True
        cmd = mock_run.call_args[0][0]
        cmd_str = " ".join(str(a) for a in cmd)
        assert "avr109" in cmd_str
        assert "m32u4" in cmd_str
        assert "57600" in cmd_str


class TestFlashVerifyOperation:
    """avrdude verify reads flash back for comparison."""

    def test_verify_uses_read_flag(self, monkeypatch, fake_hex_path):
        """Verify should use :v: instead of :w:."""
        from firmforge.providers.arduino.flash import ArduinoFlashProvider

        _mock_port(monkeypatch, "COM3")
        provider = ArduinoFlashProvider(_board_config("ATmega328P"))

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
            result = provider.verify(fake_hex_path)

        assert result.success is True
        cmd = mock_run.call_args[0][0]
        cmd_str = " ".join(str(a) for a in cmd)
        assert ":v:" in cmd_str  # verify, not write


class TestFlashErrorHandling:
    """Error conditions and edge cases."""

    def test_missing_hex_file(self, monkeypatch):
        """Non-existent hex → FlashResult.success=False."""
        from firmforge.providers.arduino.flash import ArduinoFlashProvider

        _mock_port(monkeypatch, "COM3")
        provider = ArduinoFlashProvider(_board_config())

        result = provider.flash("/nonexistent/path.hex")

        assert result.success is False
        assert "not found" in result.stderr.lower()

    def test_no_com_port(self, monkeypatch, tmp_path):
        """No COM port detected → fail before avrdude call."""
        from firmforge.providers.arduino.flash import ArduinoFlashProvider

        monkeypatch.setattr(ArduinoFlashProvider, "detect_port", lambda self: None)
        provider = ArduinoFlashProvider(_board_config())
        hex_file = tmp_path / "test.hex"
        hex_file.write_text(":00000001FF")
        result = provider.flash(str(hex_file))

        assert result.success is False
        assert "No COM port" in (result.stderr or "")

    def test_avrdude_failure_all_bauds(self, monkeypatch, fake_hex_path):
        """All baud rates fail → final FlashResult with error."""
        from firmforge.providers.arduino.flash import ArduinoFlashProvider

        _mock_port(monkeypatch, "COM3")
        provider = ArduinoFlashProvider(_board_config())

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1, stdout="", stderr="avrdude: programmer not responding"
            )
            result = provider.flash(fake_hex_path)

        assert result.success is False
        assert "Failed" in result.stderr or "failed" in result.stderr.lower()

    def test_rc0_with_port_error_is_not_success(self, monkeypatch, fake_hex_path):
        """rc=0 但端口打不开 → 必须是失败。

        实测（2026-10-21，Nano 的 CH340 端点失效）：avrdude 打印
        "unable to open port COM5" 后仍返回 0，旧逻辑据此报 Flash SUCCESS
        (0 bytes) —— S4 是阻断点，假通过比假失败危险得多。
        """
        from firmforge.providers.arduino.flash import ArduinoFlashProvider

        _mock_port(monkeypatch, "COM3")
        provider = ArduinoFlashProvider(_board_config())

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="avrdude error: unable to open port COM3 for programmer arduino\n"
                       "Avrdude done.  Thank you.\n",
                stderr="",
            )
            result = provider.flash(fake_hex_path)

        assert result.success is False

    def test_no_byte_evidence_falls_back_to_verify(self, monkeypatch, fake_hex_path):
        """rc=0 但没有字节证据时，用回读校验兜底，而不是猜成功或猜失败。"""
        from firmforge.providers.arduino.flash import ArduinoFlashProvider

        _mock_port(monkeypatch, "COM3")
        provider = ArduinoFlashProvider(_board_config())

        write_ok = MagicMock(returncode=0, stdout="avrdude: writing flash (100 bytes)\n",
                             stderr="")
        verify_ok = MagicMock(returncode=0, stdout="avrdude: 100 bytes verified\n", stderr="")

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [write_ok, verify_ok]
            result = provider.flash(fake_hex_path)

        assert result.success is True
        assert result.bytes_written == -1          # 校验通过但字节数未知
        assert mock_run.call_count == 2
        assert ":v:" in " ".join(str(a) for a in mock_run.call_args[0][0])

    def test_no_byte_evidence_and_verify_fails(self, monkeypatch, fake_hex_path):
        """没有字节证据、回读也失败 → 失败。"""
        from firmforge.providers.arduino.flash import ArduinoFlashProvider

        _mock_port(monkeypatch, "COM3")
        provider = ArduinoFlashProvider(_board_config())

        empty = MagicMock(returncode=0, stdout="done", stderr="")
        verify_fail = MagicMock(returncode=1, stdout="", stderr="avrdude: verification error")

        def _fake_run(cmd, **_kwargs):
            # 回读校验自己也会遍历波特率，所以按命令行内容区分，而不是按调用序号
            return verify_fail if any(":v:" in str(a) for a in cmd) else empty

        with patch("subprocess.run", side_effect=_fake_run):
            result = provider.flash(fake_hex_path)

        assert result.success is False


class TestMCUMapCompleteness:
    """Chip → avrdude part name mapping."""

    def test_known_chips_resolve_correctly(self):
        """All registered MCUs resolve to their avrdude part names."""
        from firmforge.providers.arduino.flash import ArduinoFlashProvider

        expected = {
            "ATmega2560": "m2560",
            "ATmega328P": "m328p",
            "ATmega328":  "m328p",
            "ATmega168P": "m168p",
            "ATmega168":  "m168p",
            "ATmega88P":  "m88p",
            "ATmega48P":  "m48p",
            "ATmega32U4": "m32u4",
        }
        for chip, part in expected.items():
            provider = ArduinoFlashProvider(_board_config(chip))
            assert provider._mcu_part == part, f"MCU {chip} → {part}"

    def test_unknown_chip_raises_flash_error(self):
        """Unsupported chip → raises FlashError (not silent m2560 fallback)."""
        from firmforge.providers.arduino.flash import ArduinoFlashProvider, FlashError

        with pytest.raises(FlashError, match="Unknown MCU"):
            ArduinoFlashProvider(_board_config("ATtiny85"))


class TestBaudRateResolution:
    """Baud rate selection per chip."""

    def test_m328p_default_baud(self):
        from firmforge.providers.arduino.flash import ArduinoFlashProvider
        provider = ArduinoFlashProvider(_board_config("ATmega328P"))
        assert provider._resolve_baud() == 115200

    def test_m32u4_default_baud(self):
        from firmforge.providers.arduino.flash import ArduinoFlashProvider
        provider = ArduinoFlashProvider(_board_config("ATmega32U4"))
        assert provider._resolve_baud() == 57600

    def test_bootloader_baud_override(self):
        """board_config bootloader.baud_rate overrides default."""
        from firmforge.providers.arduino.flash import ArduinoFlashProvider

        cfg = _board_config("ATmega328P")
        cfg["bootloader"] = {"baud_rate": 57600}
        provider = ArduinoFlashProvider(cfg)
        fallbacks = provider._get_baud_fallbacks()
        assert 57600 in fallbacks


class TestFlashResultStructure:
    """FlashResult carries all expected fields."""

    def test_successful_result_structure(self, monkeypatch, fake_hex_path):
        from firmforge.providers.arduino.flash import ArduinoFlashProvider

        _mock_port(monkeypatch, "COM3")
        provider = ArduinoFlashProvider(_board_config())

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="avrdude: 16384 bytes of flash written\navrdude done.",
                stderr="",
            )
            result = provider.flash(fake_hex_path)

        assert result.success is True
        assert result.elapsed_ms > 0
        assert result.bytes_written > 0
        assert "avrdude done" in result.stdout
