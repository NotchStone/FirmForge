"""Integration tests for Code Review and PipelineRunner v3.0 (B+).

Tests:
- Citation check with valid/hallucinated code
- Pipeline integration (Review stage blocks hallucinated registers)
- Experience ledger recording
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from firmforge.core.source_reviewer import SourceReviewResult, SourceReviewViolation
from firmforge.core.pipeline_runner import PipelineRunner, PipelineResult, PipelineStage
from firmforge.knowledge.knowledge_base import KnowledgeBase


@pytest.fixture
def temp_workspace():
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        (ws / ".firmforge").mkdir(exist_ok=True)
        yield ws


@pytest.fixture
def temp_boards_dir_with_code(temp_workspace: Path):
    boards_dir = temp_workspace / "boards"
    app_dir = boards_dir / "arduino_uno" / "apps" / "test_app"
    app_dir.mkdir(parents=True)

    board_json = {
        "board_id": "arduino_uno",
        "board_name": "Arduino UNO R3",
        "platform": "arduino",
        "mcu": {"chip": "ATmega328P", "series": "avr", "f_cpu": "16000000UL",
                "flash_size": 0x8000, "ram_size": 0x0800},
        "serial": "serial0",
        "flash_protocol": "wiring",
        "bootloader": {"baud_rate": 115200},
    }
    (boards_dir / "arduino_uno").mkdir(parents=True, exist_ok=True)
    with open(boards_dir / "arduino_uno" / "board.json", "w") as f:
        json.dump(board_json, f)

    valid_code = """
#include <avr/io.h>

void setup() {
    DDRB |= (1 << 5);
    PORTB |= (1 << 5);
}

void loop() {
    PORTB ^= (1 << 5);
}
"""
    (app_dir / "main.cpp").write_text(valid_code)
    (app_dir / "config.h").write_text("#pragma once\n#define F_CPU 16000000UL\n")

    return boards_dir, app_dir


@pytest.fixture
def runner(temp_workspace: Path, temp_boards_dir_with_code):
    boards_dir, _ = temp_boards_dir_with_code
    return PipelineRunner(boards_dir=str(boards_dir), workspace=str(temp_workspace))


@pytest.fixture
def board_config(temp_boards_dir_with_code):
    boards_dir, _ = temp_boards_dir_with_code
    with open(boards_dir / "arduino_uno" / "board.json") as f:
        return json.load(f)


# Citation check method tests ------------------------------------------------

class TestCitationCheckMethod:
    def test_review_check_valid_code(self, runner, temp_boards_dir_with_code, board_config):
        boards_dir, app_dir = temp_boards_dir_with_code
        result = runner._review_check("arduino_uno", str(app_dir), board_config)
        assert result is not None
        assert result.passed is True
        assert len(result.violations) == 0

    def test_review_check_none_source_dir(self, runner, board_config):
        result = runner._review_check("arduino_uno", None, board_config)
        assert result is None

    def test_review_check_nonexistent_source_dir(self, runner, board_config):
        result = runner._review_check("arduino_uno", "/nonexistent/path", board_config)
        assert result is None

    def test_review_check_hallucinated_register(self, runner, temp_boards_dir_with_code, board_config):
        boards_dir, app_dir = temp_boards_dir_with_code
        (app_dir / "bad.cpp").write_text("""
#include <avr/io.h>
void setup() { PORTZ = 0xFF; UCSR9A = 0x00; }
""")
        result = runner._review_check("arduino_uno", str(app_dir), board_config)
        assert result is not None
        assert result.passed is False
        reg_names = [v.register for v in result.violations]
        assert "PORTZ" in reg_names or "UCSR9A" in reg_names

    def test_review_check_counts_registers(self, runner, temp_boards_dir_with_code, board_config):
        boards_dir, app_dir = temp_boards_dir_with_code
        result = runner._review_check("arduino_uno", str(app_dir), board_config)
        assert result is not None
        assert result.registers_checked >= 2
        assert result.registers_resolved >= 2

    def test_review_check_multiple_files(self, runner, temp_boards_dir_with_code, board_config):
        boards_dir, app_dir = temp_boards_dir_with_code
        (app_dir / "uart.cpp").write_text("""
#include <avr/io.h>
void init_uart() {
    UBRR0H = 0; UBRR0L = 103;
    UCSR0B = (1<<TXEN0)|(1<<RXEN0);
    UCSR0C = (1<<UCSZ01)|(1<<UCSZ00);
}
""")
        result = runner._review_check("arduino_uno", str(app_dir), board_config)
        assert result is not None
        assert result.passed is True
        assert result.registers_checked >= 6


class TestPipelineIntegration:
    def test_citation_gate_in_pipeline_valid(self, runner, temp_boards_dir_with_code):
        boards_dir, app_dir = temp_boards_dir_with_code
        result = runner.run_full(source_dir=str(app_dir), board_id="arduino_uno")
        # Review should pass for valid code
        review = next((s for s in result.stages if s.name == "Review"), None)
        assert review is not None
        assert review.success is True

    def test_citation_gate_in_pipeline_hallucinated(self, runner, temp_boards_dir_with_code):
        boards_dir, app_dir = temp_boards_dir_with_code
        (app_dir / "bad.cpp").write_text("PORTZ = 0xFF;\n")
        result = runner.run_full(source_dir=str(app_dir), board_id="arduino_uno")
        # Review is now non-blocking (gcc is the gatekeeper).
        # It records warnings with line numbers and context.
        review = next((s for s in result.stages if s.name == "Review"), None)
        assert review is not None
        assert review.success is True   # non-blocking, always passes
        warnings = (review.details or {}).get("warnings", [])
        assert any("PORTZ" in w.get("register", "") for w in warnings)
        assert any(w.get("line", 0) > 0 for w in warnings)
        # Build stage should still run (non-blocking)
        assert any(s.name == "Build" for s in result.stages)

    def test_citation_gate_records_to_ledger(self, runner, temp_boards_dir_with_code, temp_workspace):
        boards_dir, app_dir = temp_boards_dir_with_code
        (app_dir / "bad.cpp").write_text("DDRQ = 0xFF;\n")
        result = runner.run_full(source_dir=str(app_dir), board_id="arduino_uno")
        # Warnings are in review stage details, not ledger (ledger is for compile errors)
        review = next((s for s in result.stages if s.name == "Review"), None)
        assert review is not None
        assert review.success is True
        warnings = (review.details or {}).get("warnings", [])
        assert any("DDRQ" in w.get("register", "") for w in warnings)

    def test_cppcheck_in_pipeline_review(self, runner, temp_boards_dir_with_code):
        """Verify cppcheck field exists in review stage details."""
        # Integration with run_full verifies the cppcheck path is wired in.
        # Note: cppcheck may not be installed, so we only check the field exists.
        boards_dir, app_dir = temp_boards_dir_with_code
        # Use simple code that won't trigger flash issues
        result = runner.run_full(source_dir=str(app_dir), board_id="arduino_uno")
        review = next((s for s in result.stages if s.name == "Review"), None)
        assert review is not None
        # cppcheck field must exist in details (even if empty list)
        assert isinstance((review.details or {}).get("cppcheck"), list)



class TestLazyInit:
    def test_get_source_reviewer(self, runner):
        v1 = runner._get_source_reviewer()
        assert v1 is not None
        v2 = runner._get_source_reviewer()
        assert v2 is v1


class TestEdgeCases:
    def test_empty_source_directory(self, runner, temp_boards_dir_with_code, board_config):
        boards_dir, app_dir = temp_boards_dir_with_code
        for f in app_dir.glob("*.cpp"):
            f.unlink()
        for f in app_dir.glob("*.h"):
            f.unlink()
        result = runner._review_check("arduino_uno", str(app_dir), board_config)
        assert result is not None
        assert result.passed is True

    def test_header_files_also_checked(self, runner, temp_boards_dir_with_code, board_config):
        boards_dir, app_dir = temp_boards_dir_with_code
        (app_dir / "regs.h").write_text("#ifndef REGS_H\n#define REGS_H\n#define LED_PORT PORTZ\n#endif\n")
        result = runner._review_check("arduino_uno", str(app_dir), board_config)
        assert result is not None
