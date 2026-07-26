"""HIL (Hardware-in-the-Loop) Framework -- serial assert + collection.

规划 §3.2: Infrastructure layer. MVP: assert + serial collection (pyserial).
Stage 4+: OpenOCD/GDB register readback for hard evidence.

Usage:
    hil = HILFramework()
    hil.connect("COM7", 9600)
    result = hil.assert_output("Hello World", timeout_ms=2000)
    if result.success:
        print("Board startup message verified")
"""

from __future__ import annotations

import logging
import time
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class HILTestAssertion:
    """A single HIL test assertion."""
    name: str
    description: str = ""
    expected: str = ""           # Expected string pattern in serial output
    pattern_type: str = "contains"  # "contains" | "exact" | "regex" | "starts_with"
    timeout_ms: float = 2000
    send_before: str | None = None  # Data to send to board before checking
    success: bool | None = None
    actual_output: str = ""
    elapsed_ms: float = 0.0


@dataclass
class HILTestResult:
    """Aggregated HIL test result."""
    success: bool = False
    assertions: list[HILTestAssertion] = field(default_factory=list)
    assertions_passed: int = 0
    assertions_failed: int = 0
    total_elapsed_ms: float = 0.0
    raw_output: str = ""


class HILFramework:
    """Hardware-in-the-loop test framework.

    Connects via pyserial, runs assertions against serial output,
    and produces structured test results for the verify stage.
    """

    def __init__(self) -> None:
        self._serial = None
        self._connected = False
        self._port: str = ""
        self._baudrate: int = 9600
        self._timeout: float = 1.0

    @property
    def connected(self) -> bool:
        return self._connected

    # -- Connection --

    def connect(self, port: str, baudrate: int = 9600,
                timeout: float = 1.0) -> bool:
        """Open serial connection to the board.

        Returns True on success, False on failure.
        """
        try:
            import serial
        except ImportError:
            logger.error("pyserial not installed — HIL disabled")
            return False

        try:
            self._serial = serial.Serial(port, baudrate, timeout=timeout)
            self._port = port
            self._baudrate = baudrate
            self._timeout = timeout
            self._connected = True

            # Wait for board to reset after connection
            time.sleep(2.0)

            # Flush any boot noise
            self._serial.reset_input_buffer()

            logger.info("HIL connected: %s @ %d baud", port, baudrate)
            return True
        except (serial.SerialException, OSError) as e:
            logger.error("HIL connect failed: %s", e)
            return False

    def disconnect(self) -> None:
        """Close serial connection."""
        if self._serial and self._serial.is_open:
            self._serial.close()
        self._connected = False
        logger.info("HIL disconnected")

    def set_dtr(self, state: bool) -> None:
        """Toggle DTR line (triggers reset on some Arduino boards)."""
        if self._serial:
            self._serial.dtr = state

    def reset_board(self) -> None:
        """Reset board via DTR pulse."""
        self.set_dtr(False)
        time.sleep(0.1)
        self.set_dtr(True)
        time.sleep(2.0)  # Wait for bootloader + sketch start
        if self._serial:
            self._serial.reset_input_buffer()

    # -- Read --

    def read_line(self, timeout_ms: float | None = None) -> str:
        """Read a single line from serial (blocking up to timeout)."""
        if not self._connected or not self._serial:
            return ""

        if timeout_ms is not None:
            self._serial.timeout = timeout_ms / 1000.0

        try:
            line = self._serial.readline()
            if isinstance(line, bytes):
                line = line.decode("utf-8", errors="replace")
            return line.rstrip("\r\n")
        except Exception as e:
            logger.warning("HIL read error: %s", e)
            return ""

    def read_until(
        self,
        expected: str,
        timeout_ms: float = 3000,
    ) -> str:
        """Read serial output until expected string appears or timeout.

        Returns the accumulated output.
        """
        if not self._connected or not self._serial:
            return ""

        deadline = time.time() + timeout_ms / 1000.0
        buffer: list[str] = []

        while time.time() < deadline:
            remaining = max(0, deadline - time.time())
            self._serial.timeout = min(remaining, 0.5)

            try:
                line = self._serial.readline()
                if isinstance(line, bytes):
                    line = line.decode("utf-8", errors="replace")
                if line:
                    text = line.rstrip("\r\n")
                    buffer.append(text)
                    if expected in text:
                        break
            except Exception:
                break

        return "\n".join(buffer)

    def read_all(self, timeout_ms: float = 1000) -> str:
        """Read all available serial data within timeout."""
        if not self._connected or not self._serial:
            return ""

        deadline = time.time() + timeout_ms / 1000.0
        lines: list[str] = []

        while time.time() < deadline:
            remaining = max(0, deadline - time.time())
            self._serial.timeout = min(remaining, 0.1)
            try:
                line = self._serial.readline()
                if line:
                    text = line.decode("utf-8", errors="replace").rstrip("\r\n")
                    if text:
                        lines.append(text)
            except Exception:
                break

        return "\n".join(lines)

    # -- Write --

    def send(self, data: str | bytes) -> None:
        """Send data to the board."""
        if not self._connected or not self._serial:
            return
        if isinstance(data, str):
            data = data.encode("utf-8")
        self._serial.write(data)

    def send_line(self, line: str) -> None:
        """Send a line to the board (appends \\r\\n)."""
        self.send(line + "\r\n")

    # -- Assertions --

    def assert_output(
        self,
        expected: str,
        timeout_ms: float = 2000,
        pattern_type: str = "contains",
        send_before: str | None = None,
    ) -> HILTestAssertion:
        """Check if expected pattern appears in serial output.

        Args:
            expected: Expected text pattern
            timeout_ms: Max wait time in ms
            pattern_type: "contains" | "exact" | "regex" | "starts_with"
            send_before: Data to send to board before waiting

        Returns:
            HILTestAssertion with success/failure and actual output.
        """
        assertion = HILTestAssertion(
            name=f"assert_{pattern_type}",
            description=f"Expect '{expected[:40]}' in output",
            expected=expected,
            pattern_type=pattern_type,
            timeout_ms=timeout_ms,
            send_before=send_before,
        )

        if not self._connected:
            assertion.success = False
            assertion.actual_output = "<HIL not connected>"
            return assertion

        start = time.time()

        # Send trigger data if specified
        if send_before:
            self.send_line(send_before)
            time.sleep(0.1)

        # Read output
        output = self.read_until(expected, timeout_ms)
        assertion.actual_output = output
        assertion.elapsed_ms = (time.time() - start) * 1000

        # Check
        assertion.success = self._match_pattern(output, expected, pattern_type)

        if assertion.success:
            logger.info("HIL assert PASS: '%s' found", expected[:40])
        else:
            logger.warning("HIL assert FAIL: '%s' not found after %.0fms",
                           expected[:40], assertion.elapsed_ms)

        return assertion

    def assert_sequence(
        self,
        assertions: list[dict[str, Any]],
    ) -> HILTestResult:
        """Run a sequence of assertions against the board.

        Args:
            assertions: List of assertion specs:
                [
                    {"name": "startup", "expected": "Hello", "timeout_ms": 2000},
                    {"name": "echo", "expected": "HELLO", "send_before": "hello"},
                ]

        Returns:
            HILTestResult with aggregated results.
        """
        result = HILTestResult()
        start = time.time()

        for spec in assertions:
            a = self.assert_output(
                expected=spec.get("expected", ""),
                timeout_ms=spec.get("timeout_ms", 2000),
                pattern_type=spec.get("pattern_type", "contains"),
                send_before=spec.get("send_before"),
            )
            a.name = spec.get("name", a.name)
            a.description = spec.get("description", a.description)
            result.assertions.append(a)
            if a.success:
                result.assertions_passed += 1
            else:
                result.assertions_failed += 1

        result.success = result.assertions_failed == 0
        result.total_elapsed_ms = (time.time() - start) * 1000
        return result

    # -- Verify step helpers --

    def verify_startup(self, expected_message: str,
                       timeout_ms: float = 3000) -> bool:
        """Verify board sends expected startup message after reset."""
        self.reset_board()
        result = self.assert_output(expected_message, timeout_ms=timeout_ms)
        return result.success

    def verify_echo(self, test_string: str, expected_response: str,
                    timeout_ms: float = 2000) -> bool:
        """Verify board echoes input correctly (for UART echo tests)."""
        result = self.assert_output(
            expected=expected_response,
            timeout_ms=timeout_ms,
            send_before=test_string,
        )
        return result.success

    # -- Helpers --

    @staticmethod
    def _match_pattern(output: str, expected: str, pattern_type: str) -> bool:
        if pattern_type == "contains":
            return expected in output
        elif pattern_type == "exact":
            return output.strip() == expected.strip()
        elif pattern_type == "regex":
            try:
                return bool(re.search(expected, output))
            except re.error:
                return False
        elif pattern_type == "starts_with":
            return output.strip().startswith(expected.strip())
        return False
