"""Arduino TestProvider — on-hardware test adapter.

Implements TestProvider from providers/base.py.
Uses pyserial to connect to board, collect output, run assertions.
Leverages HILFramework for pattern matching and structured test results.
"""

from __future__ import annotations

import logging
from typing import Any

from firmforge.providers.base import TestProvider, TestResult, TestError
from firmforge.infrastructure.hil import HILFramework

logger = logging.getLogger(__name__)


class ArduinoTestProvider(TestProvider):
    """Arduino on-hardware test adapter (pyserial + HIL).

    Opens serial connection, collects output, runs test specifications,
    and produces structured TestResults for the verify stage.
    """

    def __init__(self, board_config: dict[str, Any]) -> None:
        super().__init__(board_config)
        self._hil = HILFramework()
        self._port: str | None = None
        self._baudrate: int = 9600

    def connect(self, port: str, baudrate: int = 9600) -> None:
        """Open serial connection to the board."""
        self._port = port
        self._baudrate = baudrate
        ok = self._hil.connect(port, baudrate)
        if not ok:
            raise TestError(f"Failed to connect to {port} @ {baudrate}")

    def disconnect(self) -> None:
        self._hil.disconnect()

    def collect_output(self, timeout_ms: float = 5000) -> str:
        """Read all available serial output."""
        return self._hil.read_all(timeout_ms)

    def run_test(
        self, test_spec: dict[str, Any], port: str | None = None,
    ) -> TestResult:
        """Execute a test specification against the board.

        test_spec format:
        {
            "name": "test_name",
            "assertions": [
                {"name": "startup", "expected": "Hello", "timeout_ms": 2000},
                {"name": "echo", "expected": "HELLO", "send_before": "hello"},
            ]
        }
        """
        if not self._hil.connected:
            if port:
                self.connect(port, self._baudrate)
            else:
                return TestResult(
                    success=False,
                    test_name=test_spec.get("name", "unknown"),
                    failures=[{"reason": "Not connected to board"}],
                )

        # Reset board to get clean startup output
        self._hil.reset_board()

        # Run assertions
        hil_result = self._hil.assert_sequence(
            test_spec.get("assertions", [])
        )

        return TestResult(
            success=hil_result.success,
            test_name=test_spec.get("name", "unknown"),
            assertions_passed=hil_result.assertions_passed,
            assertions_failed=hil_result.assertions_failed,
            serial_output=hil_result.raw_output,
            failures=[
                {"name": a.name, "expected": a.expected, "actual": a.actual_output[:80]}
                for a in hil_result.assertions if not a.success
            ],
            elapsed_ms=hil_result.total_elapsed_ms,
        )

    def send_input(self, data: bytes) -> None:
        self._hil.send(data)

    def send_line(self, line: str) -> None:
        self._hil.send_line(line)

    def verify_startup_message(
        self, expected: str, timeout_ms: float = 3000,
    ) -> bool:
        """Quick check: board sends expected startup message."""
        if not self._hil.connected:
            return False
        self._hil.reset_board()
        result = self._hil.assert_output(expected, timeout_ms=timeout_ms)
        return result.success
