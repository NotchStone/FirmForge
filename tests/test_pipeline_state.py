"""Unit tests for pipeline_state.py — fingerprint-driven incremental pipeline."""

import json
from pathlib import Path
from firmforge.core.pipeline_state import PipelineState, compute_fingerprints


class TestPipelineState:
    def test_empty_state_skips_nothing(self, tmp_path):
        state = PipelineState(Path(tmp_path))
        assert not state.should_skip_build({"board_id": "arduino_uno", "source": "abc", "hex": ""})

    def test_should_skip_build_board_match(self, tmp_path):
        state = PipelineState(Path(tmp_path))
        state.mark_done("build", hex="/some/firmware.hex")
        fps = {"board_id": "arduino_uno", "port": "COM5", "source": "abc", "hex": "def"}
        state.update_fingerprints(fps)
        state.save()

        state2 = PipelineState(Path(tmp_path))
        assert state2.should_skip_build({"board_id": "arduino_uno", "source": "abc"})

    def test_board_change_invalidates_build(self, tmp_path):
        state = PipelineState(Path(tmp_path))
        fps = {"board_id": "arduino_uno", "port": "COM5", "source": "abc", "hex": "def"}
        state.update_fingerprints(fps)
        state.save()

        state2 = PipelineState(Path(tmp_path))
        assert not state2.should_skip_build({"board_id": "arduino_nano", "source": "abc"})

    def test_port_change_invalidates_flash(self, tmp_path):
        state = PipelineState(Path(tmp_path))
        fps = {"board_id": "arduino_uno", "port": "COM5", "source": "abc", "hex": "def"}
        state.update_fingerprints(fps)
        state.save()

        state2 = PipelineState(Path(tmp_path))
        assert not state2.should_skip_flash({"board_id": "arduino_uno", "port": "COM8", "source": "abc", "hex": "def"})

    def test_fingerprints_persistence(self, tmp_path):
        state = PipelineState(Path(tmp_path))
        state.mark_done("build")
        state.mark_failed("flash", "avrdude timeout")
        state.save()

        assert Path(tmp_path, ".firmforge", "state.json").exists()
        data = json.loads(Path(tmp_path, ".firmforge", "state.json").read_text())
        assert data["stages"]["build"]["status"] == "done"
        assert data["stages"]["flash"]["status"] == "failed"
        assert data["last_error"]["stage"] == "flash"

    def test_clear_removes_file(self, tmp_path):
        state = PipelineState(Path(tmp_path))
        state.mark_done("detect")
        state.save()
        assert Path(tmp_path, ".firmforge", "state.json").exists()
        PipelineState.clear(Path(tmp_path))
        assert not Path(tmp_path, ".firmforge", "state.json").exists()
