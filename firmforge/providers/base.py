"""Provider base classes -- the architectural boundary that MUST NOT be violated.

规划 v2.3 R6: providers/base.py is the boundary. New boards fill adapters;
NEVER modify the core framework.

Protocol: every MCU board must supply Build + Flash + Test providers.
Each provider receives a board config dict (board.json deserialized) at init.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any


class ProviderError(Exception):
    """Base exception for all provider-level failures."""


class BuildError(ProviderError):
    """Compilation failure -- parsed from compiler output."""


class FlashError(ProviderError):
    """Flashing failure -- parsed from programmer output."""


class TestError(ProviderError):
    """On-hardware test assertion failure."""


class BuildStage(Enum):
    """Fine-grained build stages for error attribution."""
    PREPROCESS = auto()
    COMPILE = auto()
    LINK = auto()
    POST_PROCESS = auto()


@dataclass
class BuildResult:
    """Structured compilation result.

    Carries all information needed by COMPILE_FIX (§2.5):
    parse_build_errors → ai_fix_with_context → rebuild_and_verify.
    """
    success: bool
    firmware_path: str | None = None
    stdout: str = ""
    stderr: str = ""
    elapsed_ms: float = 0.0
    errors: list[BuildDiagnostic] = field(default_factory=list)
    warnings: list[BuildDiagnostic] = field(default_factory=list)


@dataclass
class BuildDiagnostic:
    """Single compiler diagnostic -- file/line/severity/message."""
    severity: str  # "error" | "warning"
    file: str = ""
    line: int = 0
    column: int = 0
    message: str = ""
    raw: str = ""  # original line for LLM context


@dataclass
class FlashResult:
    """Structured flashing result.

    Carries information for FLASH_RETRY (§2.5): max 2 retries.
    """
    success: bool
    bytes_written: int = 0
    stdout: str = ""
    stderr: str = ""
    elapsed_ms: float = 0.0


@dataclass
class TestResult:
    """Structured on-hardware test result.

    Carries information for TEST_DIAGNOSE (§2.5).
    """
    success: bool
    test_name: str = ""
    assertions_passed: int = 0
    assertions_failed: int = 0
    serial_output: str = ""  # captured serial output for verdict analysis
    failures: list[dict[str, Any]] = field(default_factory=list)
    elapsed_ms: float = 0.0


class BuildProvider(abc.ABC):
    """Abstract compiler adapter.

    Each MCU platform implements its own BuildProvider:
      - avr-gcc for Arduino / AVR
    Provider receives board config at __init__.

    Subclass contract:
      - build(source_dir) -> BuildResult (blocking)
      - parse_build_errors(stderr) -> list[BuildDiagnostic] (for AI fix)
    """

    def __init__(self, board_config: dict[str, Any]) -> None:
        self._board_config = board_config

    @property
    def mcu_chip(self) -> str:
        return self._board_config.get("mcu", {}).get("chip", "unknown")

    @abc.abstractmethod
    def build(self, source_dir: str, output_dir: str | None = None) -> BuildResult:
        """Compile source code into firmware. Blocking call."""

    @abc.abstractmethod
    def parse_build_errors(self, stderr: str) -> list[BuildDiagnostic]:
        """Parse compiler stderr into structured diagnostics.

        This is the first step of COMPILE_FIX (§2.5).
        Output feeds directly into LLM context for AI fix.
        """

    def get_toolchain_version(self) -> str:
        """Return toolchain version string for platform_config.yaml tracking."""
        return "unknown"


class FlashProvider(abc.ABC):
    """Abstract programmer adapter.

    Each MCU platform implements its own FlashProvider:
      - avrdude for Arduino / AVR

    Subclass contract:
      - detect_port() -> str | None
      - flash(firmware_path) -> FlashResult (blocking)
    """

    def __init__(self, board_config: dict[str, Any]) -> None:
        self._board_config = board_config

    @abc.abstractmethod
    def detect_port(self) -> str | None:
        """Scan for connected board; return port identifier or None.

        pyserial enumerate + VID/PID match for USB devices.
        Returns e.g. "COM5" or "/dev/ttyACM0".
        """

    @abc.abstractmethod
    def flash(self, firmware_path: str) -> FlashResult:
        """Flash firmware onto MCU. Blocking call."""

    @abc.abstractmethod
    def verify(self, firmware_path: str) -> FlashResult:
        """Verify flashed firmware against file."""

    def get_programmer_version(self) -> str:
        """Return programmer version string."""
        return "unknown"


class TestProvider(abc.ABC):
    """Abstract on-hardware test adapter.

    Captures serial output, runs assertions, collects evidence
    for verify stage .

    Subclass contract:
      - run_test(test_spec) -> TestResult
      - serial_capture() -> str (raw serial output)
    """

    def __init__(self, board_config: dict[str, Any]) -> None:
        self._board_config = board_config

    @abc.abstractmethod
    def connect(self, port: str, baudrate: int = 115200) -> None:
        """Open serial connection to the board."""

    @abc.abstractmethod
    def disconnect(self) -> None:
        """Close serial connection."""

    @abc.abstractmethod
    def collect_output(self, timeout_ms: float = 5000) -> str:
        """Read buffered serial output."""

    @abc.abstractmethod
    def run_test(
        self, test_spec: dict[str, Any], port: str | None = None
    ) -> TestResult:
        """Execute a test specification against the board."""

    @abc.abstractmethod
    def send_input(self, data: bytes) -> None:
        """Send data to the board's serial port (for interactive tests)."""
