"""Unit tests for experience_ledger.py."""

import json
import pytest
from firmforge.core.experience_ledger import ExperienceLedger, Lesson


class TestExperienceLedger:
    """Tests for the experience ledger (append-only JSONL)."""

    def test_record_and_search(self, temp_ledger_path):
        ledger = ExperienceLedger(temp_ledger_path)

        ledger.record(Lesson(
            error_pattern="undefined_reference",
            fix_description="add -lm to linker flags",
            mcu_platform="arduino",
            tool="avr-gcc",
            resolution_success=True,
        ))

        results = ledger.search("undefined_reference")
        assert len(results) == 1
        assert results[0].fix_description == "add -lm to linker flags"

    def test_search_by_platform(self, temp_ledger_path):
        ledger = ExperienceLedger(temp_ledger_path)

        ledger.record(Lesson(error_pattern="e1", fix_description="f1",
                             mcu_platform="arduino"))
        ledger.record(Lesson(error_pattern="e2", fix_description="f2",
                             mcu_platform="avr"))

        results = ledger.search(platform="arduino")
        assert len(results) == 1
        assert results[0].mcu_platform == "arduino"

    def test_search_with_keyword(self, temp_ledger_path):
        ledger = ExperienceLedger(temp_ledger_path)

        ledger.record(Lesson(
            error_pattern="stk500", fix_description="check wiring",
            mcu_platform="arduino", tool="avrdude",
        ))
        ledger.record(Lesson(
            error_pattern="undefined_reference", fix_description="missing -lm",
            mcu_platform="arduino", tool="avr-gcc",
        ))

        results = ledger.search("stk")
        assert len(results) == 1
        assert results[0].error_pattern == "stk500"

    def test_get_hints(self, temp_ledger_path):
        ledger = ExperienceLedger(temp_ledger_path)
        ledger.record(Lesson(
            error_pattern="undefined_reference",
            fix_description="add -lm to linker flags",
            mcu_platform="arduino",
            resolution_success=True,
        ))

        hints = ledger.get_hints(
            "undefined reference to 'sin'", platform="arduino"
        )
        assert len(hints) > 0
        assert "add -lm" in hints[0]

    def test_get_hints_excludes_failures(self, temp_ledger_path):
        ledger = ExperienceLedger(temp_ledger_path)
        ledger.record(Lesson(
            error_pattern="timeout", fix_description="tried reconnecting",
            resolution_success=False,
        ))
        ledger.record(Lesson(
            error_pattern="undefined_reference",
            fix_description="add -lm",
            resolution_success=True,
        ))

        hints = ledger.get_hints("timeout")
        assert len(hints) == 0  # only unsuccessful lesson exists

    def test_persistence(self, temp_ledger_path):
        ledger = ExperienceLedger(temp_ledger_path)
        ledger.record(Lesson(error_pattern="e1", fix_description="f1"))
        ledger.record(Lesson(error_pattern="e2", fix_description="f2"))

        # Re-open and verify
        ledger2 = ExperienceLedger(temp_ledger_path)
        assert ledger2.stats()["total_lessons"] == 2

    def test_stats(self, temp_ledger_path):
        ledger = ExperienceLedger(temp_ledger_path)
        ledger.record(Lesson(error_pattern="e1", fix_description="f1",
                             mcu_platform="arduino", resolution_success=True))
        ledger.record(Lesson(error_pattern="e1", fix_description="f1b",
                             mcu_platform="arduino", resolution_success=False))
        ledger.record(Lesson(error_pattern="e2", fix_description="f2",
                             mcu_platform="avr", resolution_success=True))

        stats = ledger.stats()
        assert stats["total_lessons"] == 3
        assert stats["success_rate"] == pytest.approx(2 / 3)
        assert stats["by_platform"]["arduino"] == 2
        assert stats["by_platform"]["avr"] == 1
        assert len(stats["top_patterns"]) == 2  # e1 (2) + e2 (1)

    def test_record_from_recovery(self, temp_ledger_path):
        ledger = ExperienceLedger(temp_ledger_path)
        lesson = ledger.record_from_recovery(
            state="compile_fix",
            error_message="undefined reference to 'main'",
            fix_applied="added main.c to build",
            source_file="apps/blink/main.c",
            platform="arduino",
            board="arduino_mega",
            tool="avr-gcc",
            success=True,
        )

        assert lesson.error_pattern == "undefined_reference"
        assert lesson.mcu_platform == "arduino"

    def test_empty_ledger(self, temp_ledger_path):
        # Non-existent ledger file
        ledger = ExperienceLedger(temp_ledger_path)
        assert ledger.stats()["total_lessons"] == 0
        assert ledger.search("anything") == []
