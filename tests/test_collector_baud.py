"""Tests for serial_config.json loading in the collector."""

import json

from firmforge.core.pipeline_runner import PipelineRunner


def _runner():
    return PipelineRunner(boards_dir="boards", workspace=".")


class TestLoadSerialConfig:
    def test_missing_config_uses_defaults(self, temp_dir):
        r = _runner()
        baud, parity = r._load_serial_config(str(temp_dir), 9600, "None")
        assert baud == 9600
        assert parity == "None"

    def test_config_file_overrides_defaults(self, temp_dir):
        (temp_dir / "serial_config.json").write_text(
            json.dumps({"baud": 57600, "parity": "Even"}), encoding="utf-8")
        r = _runner()
        baud, parity = r._load_serial_config(str(temp_dir), 9600, "None")
        assert baud == 57600
        assert parity == "Even"

    def test_corrupt_config_falls_back(self, temp_dir):
        (temp_dir / "serial_config.json").write_text("{not json", encoding="utf-8")
        r = _runner()
        baud, parity = r._load_serial_config(str(temp_dir), 19200, "Odd")
        assert baud == 19200
        assert parity == "Odd"

    def test_partial_config_keeps_defaults(self, temp_dir):
        (temp_dir / "serial_config.json").write_text(
            json.dumps({"baud": 115200}), encoding="utf-8")
        r = _runner()
        baud, parity = r._load_serial_config(str(temp_dir), 9600, "None")
        assert baud == 115200
        assert parity == "None"
