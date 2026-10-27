"""Tests for the Confidence Scorer (规划 §2.7 置信度评分).

Tests scoring of register accesses, baud rate configs, pin assignments,
and overall confidence threshold behavior.
"""

from __future__ import annotations

import pytest

from firmforge.core.source_reviewer import SourceReviewer
from firmforge.core.confidence_scorer import (
    ConfidenceCheck,
    ConfidenceReport,
    ConfidenceScorer,
    DEFAULT_CONFIDENCE_THRESHOLD,
)
from firmforge.knowledge.knowledge_base import KnowledgeBase


# Fixtures ------------------------------------------------------------------

@pytest.fixture
def kb() -> KnowledgeBase:
    kb = KnowledgeBase()
    kb.load_reference("avr", chip="atmega2560")
    return kb


@pytest.fixture
def scorer(kb: KnowledgeBase) -> ConfidenceScorer:
    return ConfidenceScorer(kb)


# Data structure tests ------------------------------------------------------

class TestConfidenceCheck:
    def test_default_values(self):
        c = ConfidenceCheck(category="register", identifier="PORTB")
        assert c.score == 0.0
        assert c.resolved is False

    def test_needs_review_below_threshold(self):
        c = ConfidenceCheck(category="register", identifier="TEST", score=30)
        assert c.needs_review(58) is True

    def test_needs_review_above_threshold(self):
        c = ConfidenceCheck(category="register", identifier="TEST", score=90)
        assert c.needs_review(58) is False

    def test_needs_review_at_threshold(self):
        c = ConfidenceCheck(category="register", identifier="TEST", score=58)
        assert c.needs_review(58) is False  # >= threshold, not >


class TestConfidenceReport:
    def test_defaults(self):
        r = ConfidenceReport()
        assert r.overall_score == 100.0
        assert r.needs_review is False
        assert r.review_items == []

    def test_summary(self):
        r = ConfidenceReport(
            checks=[ConfidenceCheck(category="register", identifier="PORTB", score=100)],
            overall_score=100.0,
        )
        s = r.summary()
        assert "100%" in s
        assert "OK" in s

    def test_summary_needs_review(self):
        r = ConfidenceReport(
            checks=[ConfidenceCheck(category="register", identifier="PORTZ", score=0)],
            overall_score=30.0,
            needs_review=True,
        )
        s = r.summary()
        assert "NEEDS REVIEW" in s


# Scoring tests -------------------------------------------------------------

class TestRegisterScoring:
    def test_valid_register_high_confidence(self, scorer: ConfidenceScorer):
        code = "DDRB = 0xFF;\nPORTB = 0xFF;\n"
        report = scorer.analyze(code)
        assert report.overall_score >= 80
        reg_ids = [c.identifier for c in report.checks if c.category == "register"]
        assert "DDRB" in reg_ids
        assert "PORTB" in reg_ids

    def test_hallucinated_register_zero_confidence(self, scorer: ConfidenceScorer):
        code = "PORTZ = 0xFF;\n"
        report = scorer.analyze(code)
        # Citation will find PORTZ, each violation → 0 confidence for that register
        assert report.source_review_passed is False

    def test_multiple_registers_aggregate(self, scorer: ConfidenceScorer):
        code = """
        DDRB = 0xFF;
        PORTB = 0xFF;
        UCSR0B = (1 << TXEN0);
        UBRR0L = 103;
        """
        report = scorer.analyze(code)
        assert report.overall_score > 0
        assert len(report.checks) > 0


class TestBaudRateScoring:
    def test_valid_baud_9600(self, scorer: ConfidenceScorer):
        code = "UBRR0H = 0;\nUBRR0L = 103;\n"
        report = scorer.analyze(code)
        baud_checks = [c for c in report.checks if c.category == "baud_rate"]
        assert len(baud_checks) >= 1
        # UBRR0L=103 is exact match for 9600 baud
        for c in baud_checks:
            if c.identifier == "UBRR0L":
                assert c.score == 100.0

    def test_valid_baud_115200(self, scorer: ConfidenceScorer):
        code = "UBRR0H = 0;\nUBRR0L = 8;\n"
        report = scorer.analyze(code)
        baud_checks = [c for c in report.checks if c.category == "baud_rate"]
        for c in baud_checks:
            if c.identifier == "UBRR0L":
                assert c.score == 100.0  # 8 is exact match for 115200

    def test_unknown_baud_low_confidence(self, scorer: ConfidenceScorer):
        code = "UBRR0H = 0;\nUBRR0L = 255;\n"
        report = scorer.analyze(code)
        baud_checks = [c for c in report.checks if c.category == "baud_rate"]
        for c in baud_checks:
            if c.identifier == "UBRR0L":
                assert c.score <= 40  # 255 doesn't match any preset

    def test_baud_not_in_code_no_check(self, scorer: ConfidenceScorer):
        code = "DDRB = 0xFF;\n"
        report = scorer.analyze(code)
        baud_checks = [c for c in report.checks if c.category == "baud_rate"]
        assert len(baud_checks) == 0


class TestPinScoring:
    def test_valid_port_access(self, scorer: ConfidenceScorer):
        code = "DDRB |= (1 << 7);\nPORTB |= (1 << 7);\n"
        report = scorer.analyze(code)
        pin_checks = [c for c in report.checks if c.category == "pin"]
        assert len(pin_checks) >= 2  # DDRB and PORTB

    def test_valid_arduino_api_pin(self, scorer: ConfidenceScorer):
        code = "pinMode(13, OUTPUT);\ndigitalWrite(13, HIGH);\n"
        report = scorer.analyze(code)
        pin_checks = [c for c in report.checks if c.category == "pin"]
        assert len(pin_checks) >= 2
        pin_ids = [c.identifier for c in pin_checks]
        assert "pin13" in pin_ids

    def test_unknown_pin_low_confidence(self, scorer: ConfidenceScorer):
        code = "pinMode(100, OUTPUT);\n"
        report = scorer.analyze(code)
        pin_checks = [c for c in report.checks if c.category == "pin"]
        for c in pin_checks:
            if c.identifier == "pin100":
                assert c.score < 60


class TestOverallConfidence:
    def test_all_valid_high_confidence(self, scorer: ConfidenceScorer):
        code = """
        DDRB = 0xFF;
        PORTB = 0xFF;
        UCSR0B = (1 << RXEN0);
        UBRR0H = 0;
        UBRR0L = 103;
        pinMode(13, OUTPUT);
        """
        report = scorer.analyze(code)
        assert report.overall_score >= 80
        assert report.needs_review is False

    def test_hallucinated_low_overall(self, scorer: ConfidenceScorer):
        code = "PORTZ = 0xFF;\nUCSR9A = 0x00;\n"
        report = scorer.analyze(code)
        # Citation failed → overall should be low
        assert not report.source_review_passed
        assert report.overall_score <= 30

    def test_citation_failure_penalizes_confidence(self, scorer: ConfidenceScorer):
        code = "DDRB = 0xFF;\nPORTZ = 0xFF;\n"
        report = scorer.analyze(code)
        # Mixed: DDRB valid but PORTZ hallucinated
        assert not report.source_review_passed
        assert report.overall_score <= 30  # citation failure penalty

    def test_empty_code_full_confidence(self, scorer: ConfidenceScorer):
        report = scorer.analyze("")
        assert report.overall_score == 100.0

    def test_arduino_api_code_high_confidence(self, scorer: ConfidenceScorer):
        code = """
        pinMode(LED_BUILTIN, OUTPUT);
        Serial.begin(9600);
        digitalWrite(LED_BUILTIN, HIGH);
        delay(500);
        """
        report = scorer.analyze(code)
        # Arduino API code — no registers directly accessed
        # Should have high confidence (no violations)
        assert report.source_review_passed is True
        assert report.overall_score >= 80

    def test_mixed_valid_and_warning(self, scorer: ConfidenceScorer):
        code = """
        DDRB = 0xFF;
        PORTB = 0xFF;
        LED_PORT = 0xFF;   // user-defined macro, not in reference
        """
        report = scorer.analyze(code)
        # LED_PORT is a user macro, shouldn't block
        # DDRB and PORTB are valid
        assert report.source_review_passed is True


class TestCapAttribution:
    """`Confidence: 30%` 必须说清"为什么是 30%"。

    2026-10-27 的实际误判：一个 STM32 工程报 30%，被读成"代码质量差"。
    真相是**单个寄存器名**（`SCB->CFSR`）不在知识库里 → 源审查二值判定
    FAIL → 总分被硬压到 30%，而其余 41 项 check 的加权平均是 93%。
    这两个数字含义完全不同，日志里不给归因就等于误导。
    """

    def test_cap_reason_names_the_offending_register(self, scorer):
        code = "DDRB = 0xFF;\nPORTZ = 0xFF;\n"
        report = scorer.analyze(code)

        assert not report.source_review_passed
        assert report.cap_reason, "被硬压时必须给出原因"
        assert "PORTZ" in report.cap_reason, "要点名具体是哪个标识符"
        assert "30%" in report.cap_reason
        # 必须点出「这与其余 check 的得分无关」，否则会被读成质量差
        assert "硬压" in report.cap_reason
        assert "加权平均" in report.cap_reason

    def test_cap_reason_is_absent_when_not_capped(self, scorer):
        report = scorer.analyze("DDRB = 0xFF;\nPORTB = 0xFF;\n")
        assert report.source_review_passed is True
        assert report.cap_reason == "", "没被压过就不要解释"

    def test_cap_reason_surfaces_in_summary(self, scorer):
        report = scorer.analyze("PORTZ = 0xFF;\n")
        assert "Why:" in report.summary()

    def test_failures_carry_file_and_line(self, scorer):
        """落点要能直接跳转 —— 只有计数的话只能自己写脚本逐个文件跑。"""
        report = scorer.analyze("DDRB = 0xFF;\nPORTZ = 0xFF;\n")
        assert report.source_review_failures
        assert any("PORTZ" in f for f in report.source_review_failures)


class TestThreshold:
    def test_custom_threshold(self, kb: KnowledgeBase):
        scorer = ConfidenceScorer(kb, threshold=90.0)
        code = "DDRB = 0xFF;\n"
        report = scorer.analyze(code)
        # With threshold 90, valid code should still pass
        assert report.overall_score >= 90
        assert report.needs_review is False

    def test_default_threshold_is_58(self, scorer: ConfidenceScorer):
        assert scorer._threshold == 58


class TestIntegrationWithCitation:
    def test_citation_result_provided(self, scorer: ConfidenceScorer):
        """Pre-computed citation result should be used by the scorer."""
        code = "PORTZ = 0xFF;\n"
        validator = SourceReviewer(scorer.knowledge_base)
        cit_result = validator.validate(code)

        report = scorer.analyze(code, source_review_result=cit_result)
        assert not report.source_review_passed
        # Should not re-validate (citation_result was provided)

    def test_citation_result_not_provided_auto_runs(self, scorer: ConfidenceScorer):
        """Without pre-computed citation result, scorer should auto-validate."""
        code = "PORTZ = 0xFF;\n"
        report = scorer.analyze(code)
        assert not report.source_review_passed
