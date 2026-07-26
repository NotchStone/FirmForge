"""Tests for the Code Review Validator (规划 §2.7 引用门禁).

Tests that the validator correctly:
- Passes valid code with known registers
- Blocks hallucinated registers (PORTZ, UCSR9A, etc.)
- Correctly handles Arduino API code (no false positives)
- Reports proper line numbers and suggestions
"""

from __future__ import annotations

import pytest

from firmforge.core.source_reviewer import (
    SourceReviewResult,
    SourceReviewer,
    SourceReviewViolation,
)
from firmforge.knowledge.knowledge_base import KnowledgeBase


# Fixtures ------------------------------------------------------------------

@pytest.fixture
def kb() -> KnowledgeBase:
    kb = KnowledgeBase()
    kb.load_reference("avr", chip="atmega2560")
    return kb


@pytest.fixture
def validator(kb: KnowledgeBase) -> SourceReviewer:
    return SourceReviewer(kb)


# Data structure tests ------------------------------------------------------

class TestCitationDataStructures:
    def test_citation_violation_defaults(self):
        v = SourceReviewViolation(register="PORTZ")
        assert v.register == "PORTZ"
        assert v.field == ""
        assert v.line == 0
        assert v.severity == "error"

    def test_citation_result_defaults(self):
        r = SourceReviewResult()
        assert r.passed is True
        assert r.violations == []
        assert r.warnings == []
        assert r.registers_checked == 0
        assert r.registers_resolved == 0

    def test_citation_result_summary_pass(self):
        r = SourceReviewResult(passed=True, registers_checked=5, registers_resolved=5)
        s = r.summary()
        assert "PASS" in s

    def test_citation_result_summary_fail(self):
        r = SourceReviewResult(
            passed=False,
            violations=[SourceReviewViolation(register="PORTZ", line=3, reason="not found")],
            registers_checked=3,
            registers_resolved=2,
        )
        s = r.summary()
        assert "FAIL" in s
        assert "PORTZ" in s


# Valid code tests ----------------------------------------------------------

class TestValidCode:
    def test_valid_gpio_code(self, validator: SourceReviewer):
        code = """
        DDRB |= (1 << 7);
        PORTB |= (1 << 7);
        PORTB &= ~(1 << 7);
        """
        result = validator.validate(code)
        assert result.passed is True
        assert len(result.violations) == 0

    def test_valid_usart_code(self, validator: SourceReviewer):
        code = """
        UBRR0H = 0;
        UBRR0L = 103;
        UCSR0B = (1 << TXEN0) | (1 << RXEN0);
        UCSR0C = (1 << UCSZ01) | (1 << UCSZ00);
        """
        result = validator.validate(code)
        assert result.passed is True
        assert len(result.violations) == 0

    def test_valid_arduino_api_code(self, validator: SourceReviewer):
        """Arduino API calls should not trigger register checks."""
        code = """
        pinMode(LED_BUILTIN, OUTPUT);
        digitalWrite(LED_BUILTIN, HIGH);
        Serial.begin(9600);
        delay(500);
        """
        result = validator.validate(code)
        assert result.passed is True
        assert result.registers_checked == 0

    def test_valid_code_with_read(self, validator: SourceReviewer):
        """Register reads (not assignments) should also be validated."""
        code = """
        if (UCSR0A & (1 << UDRE0)) {
            UDR0 = 'A';
        }
        """
        result = validator.validate(code)
        # UCSR0A and UDR0 are valid, UDRE0 is a valid field
        assert result.passed is True

    def test_all_ports_valid(self, validator: SourceReviewer):
        """All 11 GPIO ports should be valid (A-G, H, J-L; no I)."""
        ports = "ABCDEFGHJKL"  # ATmega2560 skips 'I'
        code_parts = []
        for port in ports:
            code_parts.append(f"DDR{port} = 0xFF;")
            code_parts.append(f"PORT{port} = 0xFF;")
        code = "\n".join(code_parts)
        result = validator.validate(code)
        assert result.passed is True
        assert result.registers_resolved == result.registers_checked

    def test_all_usarts_valid(self, validator: SourceReviewer):
        """All 4 USARTs should be valid."""
        code_parts = []
        for n in range(4):
            code_parts.append(f"UCSR{n}A = 0;")
            code_parts.append(f"UCSR{n}B = 0;")
            code_parts.append(f"UCSR{n}C = 0;")
            code_parts.append(f"UBRR{n}L = 103;")
            code_parts.append(f"UBRR{n}H = 0;")
            code_parts.append(f"UDR{n} = 0;")
        code = "\n".join(code_parts)
        result = validator.validate(code)
        assert result.passed is True


# Hallucinated register tests -----------------------------------------------

class TestHallucinatedRegisters:
    def test_portz_blocked(self, validator: SourceReviewer):
        code = "PORTZ = 0xFF;"
        result = validator.validate(code)
        assert result.passed is False
        assert len(result.violations) == 1
        assert result.violations[0].register == "PORTZ"
        assert result.violations[0].severity == "error"

    def test_ucsr9a_blocked(self, validator: SourceReviewer):
        code = "UCSR9A = 0x00;"
        result = validator.validate(code)
        assert result.passed is False
        assert len(result.violations) == 1
        assert result.violations[0].register == "UCSR9A"

    def test_ddrq_blocked(self, validator: SourceReviewer):
        code = "DDRQ |= (1 << 7);"
        result = validator.validate(code)
        assert result.passed is False
        assert "DDRQ" in [v.register for v in result.violations]

    def test_tccr0z_blocked(self, validator: SourceReviewer):
        code = "TCCR0Z = 0x05;"
        result = validator.validate(code)
        assert result.passed is False

    def test_multiple_hallucinations(self, validator: SourceReviewer):
        code = """
        PORTZ = 0xFF;
        UCSR9A = 0x00;
        DDRQ = 0xFF;
        """
        result = validator.validate(code)
        assert result.passed is False
        assert len(result.violations) == 3

    def test_violation_has_line_number(self, validator: SourceReviewer):
        code = "\n\n\nPORTZ = 0xFF;\n"
        result = validator.validate(code)
        assert len(result.violations) == 1
        assert result.violations[0].line == 4

    def test_violation_has_reason(self, validator: SourceReviewer):
        code = "PORTZ = 0xFF;"
        result = validator.validate(code)
        assert len(result.violations) == 1
        assert "not found" in result.violations[0].reason.lower()

    def test_violation_has_suggestion(self, validator: SourceReviewer):
        code = "PORTZ = 0xFF;"
        result = validator.validate(code)
        assert len(result.violations) == 1
        assert len(result.violations[0].suggestion) > 0


# Mixed code tests ----------------------------------------------------------

class TestMixedCode:
    def test_valid_and_hallucinated(self, validator: SourceReviewer):
        code = """
        DDRB |= (1 << 7);
        PORTB |= (1 << 7);
        UCSR0B = (1 << RXEN0);
        TCCR0Z = 0x05;
        """
        result = validator.validate(code)
        assert result.passed is False
        assert result.registers_resolved == 3  # DDRB, PORTB, UCSR0B
        assert result.registers_checked == 4   # + TCCR0Z

    def test_comments_ignored(self, validator: SourceReviewer):
        code = """
        // PORTZ is a fake register mentioned in a comment
        /* UCSR9A should also be ignored in block comments */
        DDRB = 0xFF;
        """
        result = validator.validate(code)
        assert result.passed is True
        assert len(result.violations) == 0

    def test_preprocessor_ignored(self, validator: SourceReviewer):
        code = """
        #define PORTZ 0xFF
        #include <avr/io.h>
        DDRB = 0xFF;
        """
        result = validator.validate(code)
        assert result.passed is True


# File validation tests -----------------------------------------------------

class TestFileValidation:
    def test_validate_file_existing(self, validator: SourceReviewer, tmp_path):
        code = "DDRB = 0xFF;\nPORTB = 0xFF;\n"
        f = tmp_path / "test.c"
        f.write_text(code, encoding="utf-8")
        result = validator.validate_file(str(f))
        assert result.passed is True

    def test_validate_file_nonexistent(self, validator: SourceReviewer):
        result = validator.validate_file("/nonexistent/file.c")
        assert result.passed is False
        assert "File not found" in result.violations[0].reason


# Statistics tests ----------------------------------------------------------

class TestStatistics:
    def test_registers_counted(self, validator: SourceReviewer):
        code = """
        DDRB = 0xFF;
        PORTB = 0xFF;
        UCSR0B = 0;
        """
        result = validator.validate(code)
        assert result.registers_checked == 3
        assert result.registers_resolved == 3

    def test_fields_counted(self, validator: SourceReviewer):
        code = """
        UCSR0B = (1 << TXEN0) | (1 << RXEN0);
        """
        result = validator.validate(code)
        assert result.fields_checked >= 2
        assert result.fields_resolved >= 2

    def test_empty_code(self, validator: SourceReviewer):
        result = validator.validate("")
        assert result.passed is True
        assert result.registers_checked == 0
        assert result.violations == []

    def test_no_register_code(self, validator: SourceReviewer):
        code = """
        int x = 42;
        float y = 3.14;
        char* s = "hello";
        """
        result = validator.validate(code)
        assert result.passed is True
        assert result.registers_checked == 0
