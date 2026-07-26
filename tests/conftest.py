"""pytest configuration and shared fixtures."""

import json
import tempfile
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def temp_dir():
    """Temporary directory for file-based tests."""
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def temp_ledger_path(temp_dir):
    """Temporary ledger.jsonl path."""
    return temp_dir / "ledger.jsonl"


@pytest.fixture
def board_config():
    """Sample Arduino Mega board config matching board.json schema."""
    return {
        "board_name": "Arduino Mega 2560",
        "platform": "arduino",
        "mcu": {"series": "avr", "chip": "ATmega2560"},
        "fqbn": "arduino:avr:mega",
        "pins": {"led_builtin": 13},
        "specs": {"flash": "256 KB", "ram": "8 KB", "clock": "16 MHz"},
        "constraints": {
            "isr_forbidden": ["blocking_calls", "malloc"],
            "pin_avoid": [0, 1],
            "peripheral_rules": {"i2c": "must_open_drain"},
        },
        "features": {
            "gpio": True, "uart": True, "spi": True,
            "i2c": True, "pwm": True, "adc": True,
        },
        "schematic_source": "manual_entry",
    }
