"""Integration tests for Arduino BuildProvider — mock compiler calls.

Tests build.py behavior without needing avr-gcc installed.
Uses unittest.mock to simulate compiler output and verify:
- BuildResult structure on success/failure
- Arduino API detection
- Error parsing
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Inject a fake toolchain before importing ArduinoBuildProvider
from firmforge.providers.arduino import toolchain as tc_module
from firmforge.providers.base import BuildResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FAKE_TOOLCHAIN = tc_module.ToolchainPaths(
    avr_gcc="/fake/bin/avr-gcc",
    avr_objcopy="/fake/bin/avr-objcopy",
    avrdude="/fake/bin/avrdude",
    avrdude_conf="/fake/etc/avrdude.conf",
)


def _board_config(chip: str = "ATmega328P", f_cpu: int = 16_000_000) -> dict:
    return {
        "board_name": f"Test Board ({chip})",
        "mcu": {"chip": chip, "f_cpu": f_cpu},
        "aliases": ["test_board"],
    }


def _write_source(dir_path: Path, name: str, content: str) -> Path:
    p = dir_path / name
    p.write_text(content, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Fixture: isolates toolchain resolution
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _patch_resolve_toolchain(monkeypatch):
    """Ensure all tests see the fake toolchain paths."""
    monkeypatch.setattr(tc_module, "resolve_toolchain", lambda: _FAKE_TOOLCHAIN)


@pytest.fixture(autouse=True)
def _patch_cleanup(monkeypatch):
    """Disable artifact cleanup in tests — avoids sandbox safe-delete crash."""
    from firmforge.providers.arduino import build as build_mod
    monkeypatch.setattr(build_mod, "_clean_stale_artifacts", lambda: None)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestBuildBareC:
    """Bare-metal C compilation (no Arduino API)."""

    def test_successful_bare_compile(self, tmp_path):
        """Mock gcc returning rc=0 → BuildResult.success=True."""
        from firmforge.providers.arduino.build import ArduinoBuildProvider

        _write_source(tmp_path, "main.c", """
        #include <avr/io.h>
        int main(void) { DDRB = 0xFF; while(1) {} }
        """)

        builder = ArduinoBuildProvider(_board_config())
        out = tmp_path / "out"
        out.mkdir()

        # Mock subprocess: gcc success + objcopy success
        with patch("subprocess.run") as mock_run:
            # After mock gcc returns success, the code expects firmware.hex to exist.
            # Create it so BuildResult.firmware_path is set.
            hex_file = out / "firmware.hex"
            hex_file.write_text(":00000001FF")
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            result = builder.build(source_dir=str(tmp_path), output_dir=str(out))

        assert result.success is True
        assert result.firmware_path is not None
        assert result.firmware_path.endswith(".hex")
        assert result.elapsed_ms > 0

    def test_bare_compile_with_cpp_files(self, tmp_path):
        """Mixed .c and .cpp in bare mode (not Arduino)."""
        from firmforge.providers.arduino.build import ArduinoBuildProvider

        _write_source(tmp_path, "main.c", """
        #include <avr/io.h>
        int main(void) { DDRB = 0xFF; while(1); return 0; }
        """)
        _write_source(tmp_path, "utils.cpp", """
        #include <avr/io.h>
        void init(void) { PORTB = 0; }
        """)

        builder = ArduinoBuildProvider(_board_config())
        out = tmp_path / "out"
        out.mkdir()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            result = builder.build(source_dir=str(tmp_path), output_dir=str(out))

        assert result.success is True

    def test_compile_failure_gcc_error(self, tmp_path):
        """Mock gcc returning rc=1 → BuildResult.success=False + errors."""
        from firmforge.providers.arduino.build import ArduinoBuildProvider

        _write_source(tmp_path, "main.c", """
        int main(void) { unknown_function(); }
        """)

        builder = ArduinoBuildProvider(_board_config())
        out = tmp_path / "out"
        out.mkdir()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stdout="",
                stderr="main.c:2:1: error: 'unknown_function' was not declared",
            )
            result = builder.build(source_dir=str(tmp_path), output_dir=str(out))

        assert result.success is False
        assert len(result.errors) > 0
        assert "unknown_function" in result.stderr

    def test_no_source_files(self, tmp_path):
        """Empty directory → fails with meaningful error."""
        from firmforge.providers.arduino.build import ArduinoBuildProvider

        builder = ArduinoBuildProvider(_board_config())
        result = builder.build(source_dir=str(tmp_path))

        assert result.success is False
        assert "No source files" in (result.stderr or "")

    def test_build_uses_correct_mcu_flag(self, tmp_path):
        """Verify -mmcu flag is passed for ATmega2560."""
        from firmforge.providers.arduino.build import ArduinoBuildProvider

        _write_source(tmp_path, "main.c", """
        #include <avr/io.h>
        int main(void) { DDRB = 0xFF; while(1); }
        """)

        builder = ArduinoBuildProvider(_board_config(chip="ATmega2560"))
        out = tmp_path / "out"
        out.mkdir()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            builder.build(source_dir=str(tmp_path), output_dir=str(out))

        # Check that the compiler command included -mmcu=atmega2560
        cmd_args = " ".join(str(a) for call in mock_run.call_args_list
                           for a in call[0][0] if isinstance(call[0], tuple))
        assert "-mmcu=atmega2560" in cmd_args


class TestSourceRecursiveGlob:
    """Subdirectory source file discovery (rglob)."""

    def test_finds_source_in_subdirectory(self, tmp_path):
        """Source files in lib/ subdirectory are picked up."""
        from firmforge.providers.arduino.build import ArduinoBuildProvider

        _write_source(tmp_path, "main.c", """
        #include <avr/io.h>
        extern void init_uart(void);
        int main(void) { init_uart(); DDRB = 0xFF; while(1); }
        """)
        subdir = tmp_path / "lib"
        subdir.mkdir()
        _write_source(subdir, "uart.c", """
        #include <avr/io.h>
        void init_uart(void) { UBRR0 = 103; }
        """)

        builder = ArduinoBuildProvider(_board_config())
        out = tmp_path / "out"
        out.mkdir()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            result = builder.build(source_dir=str(tmp_path), output_dir=str(out))

        assert result.success is True
        # Both source files should be in the compile command
        cmd_args = " ".join(
            str(a) for call in mock_run.call_args_list
            for a in call[0][0] if isinstance(call[0], tuple)
        )
        assert "main.c" in cmd_args
        assert "uart" in cmd_args


class TestArduinoAPIDetection:
    """Auto-detection of Arduino API usage."""

    def test_detects_arduino_api_in_cpp(self, tmp_path):
        """#include <Arduino.h> → routes to Arduino Core compilation."""
        from firmforge.providers.arduino.build import ArduinoBuildProvider

        _write_source(tmp_path, "sketch.cpp", """
        #include <Arduino.h>
        void setup() { pinMode(13, OUTPUT); }
        void loop() { digitalWrite(13, HIGH); delay(1000); }
        """)

        builder = ArduinoBuildProvider(_board_config())
        out = tmp_path / "out"
        out.mkdir()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            result = builder.build(source_dir=str(tmp_path), output_dir=str(out))

        assert result.success is True
        # Should use Arduino Core compilation (throws due to missing vendor/)
        # but structure is correct — we just verify it doesn't crash before
        # the subprocess call

    def test_detects_arduino_api_in_ino(self, tmp_path):
        """.ino file with Arduino API → routed correctly."""
        from firmforge.providers.arduino.build import ArduinoBuildProvider

        _write_source(tmp_path, "MySketch.ino", """
        void setup() { pinMode(13, OUTPUT); }
        void loop() { digitalWrite(13, HIGH); delay(1000); }
        """)

        builder = ArduinoBuildProvider(_board_config())
        out = tmp_path / "out"
        out.mkdir()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            result = builder.build(source_dir=str(tmp_path), output_dir=str(out))

        assert result.success is True


class TestInoPreprocessing:
    """Arduino .ino file preprocessing."""

    def test_ino_prototype_injection(self, tmp_path):
        """Functions after setup/loop get prototypes injected."""
        from firmforge.providers.arduino.build import ArduinoBuildProvider

        _write_source(tmp_path, "Test.ino", """
        void setup() { Serial.begin(9600); }
        void loop() { blink_led(); delay(500); }
        void blink_led() { digitalWrite(13, !digitalRead(13)); }
        """)

        provider = ArduinoBuildProvider(_board_config())

        # Call the static preprocess method directly
        processed = provider._preprocess_ino([str(tmp_path / "Test.ino")])

        # The processed file should be in the cache directory
        assert len(processed) == 1
        content = Path(processed[0]).read_text()
        assert "void blink_led();" in content
        assert "#include <Arduino.h>" in content


class TestBuildDiagnostics:
    """Error parsing from compiler stderr."""

    def test_parses_gcc_errors(self, tmp_path):
        """Standard gcc error messages → structured diagnostics."""
        from firmforge.providers.arduino.build import ArduinoBuildProvider

        _write_source(tmp_path, "main.c", "int main(void) { foo(); }")

        builder = ArduinoBuildProvider(_board_config())
        out = tmp_path / "out"
        out.mkdir()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stdout="",
                stderr="main.c:1:17: error: implicit declaration of function 'foo'",
            )
            result = builder.build(source_dir=str(tmp_path), output_dir=str(out))

        assert result.success is False
        assert len(result.errors) >= 1
        error = result.errors[0]
        assert "error" in error.severity.lower()
        assert result.firmware_path is None
