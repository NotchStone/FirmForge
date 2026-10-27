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
        # 寄存器计数现在落在分项里（registers），不再往 checks 里塞逐条
        # 满分项 —— 那只是重复计数，不提供新信息。
        regs = report.category_scores["registers"]
        assert (regs.checked, regs.resolved) == (2, 2)
        assert regs.score == 100.0

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
        """DDRB/PORTB 属寄存器，计入 registers 分项，不再另算一份 pin。

        同一处引用计两次会让「一个寄存器写错」在总分里被扣两遍，也让 pins
        分项条数虚高 —— 分项的意义就是「各算各的」。
        """
        code = "DDRB |= (1 << 7);\nPORTB |= (1 << 7);\n"
        report = scorer.analyze(code)
        regs = report.category_scores["registers"]
        assert (regs.checked, regs.resolved) == (2, 2)
        assert not [c for c in report.checks if c.category == "pin"], \
            "DDR/PORT 已经被 registers 分项覆盖，不该在 pins 里再算一次"

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
        # Citation failed → registers 分项 0/2，总分随之落地
        assert not report.source_review_passed
        assert report.category_scores["registers"].resolved == 0
        assert report.overall_score <= 30

    def test_citation_failure_penalizes_locally(self, scorer: ConfidenceScorer):
        """一处错只扣它自己那一分项，不把全局打成 30%。

        旧行为：`min(30, avg)` 硬压 —— DDRB 对、PORTZ 错，总分也是 30%。
        现在：registers 分项 1/2 = 50%，其他分项不受影响。
        """
        code = "DDRB = 0xFF;\nPORTZ = 0xFF;\n"
        report = scorer.analyze(code)
        assert not report.source_review_passed
        regs = report.category_scores["registers"]
        assert (regs.checked, regs.resolved) == (2, 1)
        assert regs.score == 50.0
        # 50% 不是 30%：错的数量决定扣多少，而不是"有错就归零"
        assert report.overall_score == 50.0

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


class TestLocalizedPenalty:
    """惩罚必须落在出错的那个分项上，不能一票打死全局。

    2026-10-27 的实际误判：一个 STM32 工程报 30%，被读成"代码质量差"。
    真相是**单个寄存器名**（`SCB->CFSR`）不在知识库里 → 源审查二值判定
    FAIL → 总分被 `min(30, avg)` 硬压到 30%，而其余 41 项的加权平均是 93%。
    加了 `cap_reason` 解释只是给错误的设计写说明书 —— 数字本身仍然不可解释。

    现在：没有硬上限。分项各算各的，总分按条数加权。10 个寄存器错 2 个是
    80%，不是 30%。
    """

    def test_no_hard_cap_field(self, scorer):
        report = scorer.analyze("PORTZ = 0xFF;\n")
        assert not hasattr(report, "cap_reason"), \
            "硬上限已删除，不保留这个字段以免有人再去读它"

    def test_category_scores_present(self, scorer):
        report = scorer.analyze("DDRB = 0xFF;\nPORTZ = 0xFF;\n")
        assert set(report.category_scores) == {
            "registers", "fields", "pins", "baud_rate"}

    def test_explanation_names_the_low_category(self, scorer):
        report = scorer.analyze("DDRB = 0xFF;\nPORTZ = 0xFF;\n")
        assert "registers" in report.explanation
        assert "50%" in report.explanation

    def test_no_explanation_when_all_high(self, scorer):
        report = scorer.analyze("DDRB = 0xFF;\nPORTB = 0xFF;\n")
        assert report.source_review_passed is True
        assert report.explanation == ""

    def test_summary_shows_categories(self, scorer):
        report = scorer.analyze("PORTZ = 0xFF;\n")
        text = report.summary()
        assert "registers" in text, "分项必须进 summary，否则等于没算"
        assert "Why:" in text

    def test_failures_carry_file_and_line(self, scorer):
        """落点要能直接跳转 —— 只有计数的话只能自己写脚本逐个文件跑。"""
        report = scorer.analyze("DDRB = 0xFF;\nPORTZ = 0xFF;\n")
        assert report.source_review_failures
        assert any("PORTZ" in f for f in report.source_review_failures)
        assert any(":" in f for f in report.source_review_failures), \
            "必须带 file:line，不是裸行号"


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


class TestKnowledgeGapIsNotPunished:
    """知识库缺口不是源码的错，不该扣分。

    2026-10-27：`TIM2->RCR` 是真寄存器（gcc 认），SVD 未建模 → 库查不到 →
    旧逻辑把它当幻觉，总分被打到 30%。现在它进 `kb_gaps`，从置信度分母里
    剔除 —— 工具没判定过的东西，不能用来扣分。
    """

    def test_gap_excluded_from_denominator(self, kb):
        from firmforge.core.source_reviewer import (
            SourceReviewResult, SourceReviewViolation,
        )
        sr = SourceReviewResult(
            passed=True, registers_checked=5, registers_resolved=4,
            kb_gaps=1,
            warnings=[SourceReviewViolation(
                register="TIM2.RCR", severity="warning", kb_gap=True)],
        )
        scorer = ConfidenceScorer(kb)
        report = scorer.analyze("", source_review_result=sr)
        regs = report.category_scores["registers"]
        assert (regs.checked, regs.resolved) == (4, 4), \
            "缺口不进分母，否则 4/5 会被读成「有一个没解析」"
        assert regs.score == 100.0
        assert "未收录" in regs.note


class TestKnowledgeGapIsNotPunished:
    """知识库缺口不是源码的错，不该扣分。

    2026-10-27：`TIM2->RCR` 是真寄存器（gcc 认），SVD 未建模 → 库查不到 →
    旧逻辑把它当幻觉，总分被打到 30%。现在它进 `kb_gaps`，从置信度分母里
    剔除 —— 工具没判定过的东西，不能用来扣分。
    """

    def test_gap_excluded_from_denominator(self, kb):
        from firmforge.core.source_reviewer import (
            SourceReviewResult, SourceReviewViolation,
        )
        sr = SourceReviewResult(
            passed=True, registers_checked=5, registers_resolved=4,
            kb_gaps=1,
            warnings=[SourceReviewViolation(
                register="TIM2.RCR", severity="warning", kb_gap=True)],
        )
        scorer = ConfidenceScorer(kb)
        report = scorer.analyze("", source_review_result=sr)
        regs = report.category_scores["registers"]
        assert (regs.checked, regs.resolved) == (4, 4), \
            "缺口不进分母，否则 4/5 会被读成「有一个没解析」"
        assert regs.score == 100.0
        assert "未收录" in regs.note
