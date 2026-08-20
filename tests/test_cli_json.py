"""Phase A: CLI --json machine-readable output tests.

Covers:
  - ff context --json returns register/pin/baud reference (JSON parseable)
  - ff detect --json returns structured board info
  - ff run/build --json error paths return JSON errors
  - ff flash --json error paths return JSON errors
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def run_cli(*args: str) -> subprocess.CompletedProcess:
    """Run the ff CLI as a subprocess (harness discipline: subprocess only)."""
    return subprocess.run(
        [sys.executable, "-m", "firmforge.adapters.cli", "--json", *args],
        capture_output=True, text=True, cwd=str(ROOT), timeout=120,
    )


class TestCliJsonContext:
    def test_context_json_parseable(self):
        r = run_cli("context", "arduino_328p")
        assert r.returncode == 0, f"stderr: {r.stderr[-500:]}"
        payload = json.loads(r.stdout)  # must be pure JSON (no text pollution)
        assert "board" in payload and payload["board"] == "arduino_328p"
        assert "chip" in payload and "atmega328p" in payload["chip"].lower()
        assert isinstance(payload.get("registers"), list) and payload["registers"]
        assert "pins" in payload and payload["pins"]

    def test_context_topic_filter(self):
        r = run_cli("context", "arduino_328p", "--topic", "adc")
        assert r.returncode == 0
        payload = json.loads(r.stdout)
        assert payload["registers"], "adc topic should return registers"

    def test_context_unknown_board_returns_error_json(self):
        r = run_cli("context", "no_such_board_xyz")
        assert r.returncode == 1
        payload = json.loads(r.stdout)
        assert "error" in payload


class TestCliJsonDetect:
    def test_detect_json_structure(self):
        r = run_cli("detect")
        # returncode may vary (no board plugged in) but output must be pure JSON
        payload = json.loads(r.stdout)
        for key in ("board_id", "boards", "detected", "candidates", "board_config"):
            assert key in payload, f"missing key {key}"
        assert isinstance(payload["candidates"], list)


class TestCliJsonErrorPaths:
    def test_run_requires_app(self):
        r = run_cli("run")
        assert r.returncode == 1
        payload = json.loads(r.stdout)
        assert "error" in payload

    def test_build_requires_app(self):
        r = run_cli("build")
        assert r.returncode == 1
        payload = json.loads(r.stdout)
        assert "error" in payload

    def test_flash_requires_board(self):
        r = run_cli("flash")
        assert r.returncode == 1
        payload = json.loads(r.stdout)
        assert "error" in payload
