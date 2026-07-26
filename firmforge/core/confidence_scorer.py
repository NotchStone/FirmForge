"""Confidence Scoring (规划 §2.7 置信度评分).

Evaluates confidence in generated code values before compilation.
Key config values (pin mux, clock divider, baud rate) get confidence scores.
Below 58% threshold → warning only (not blocking), for Agent to self-assess.

Usage:
    from firmforge.core.confidence_scorer import ConfidenceScorer, ConfidenceReport

    scorer = ConfidenceScorer(knowledge_base)
    report = scorer.analyze(source_code, board_config)

    if report.overall_score < 58:
        print(f"NEEDS REVIEW: {report.summary()}")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from firmforge.core.source_reviewer import SourceReviewResult, SourceReviewer
from firmforge.knowledge.knowledge_base import KnowledgeBase

logger = logging.getLogger(__name__)

# Default threshold: below this → human review (规划 §2.7)
DEFAULT_CONFIDENCE_THRESHOLD = 58.0


@dataclass
class ConfidenceCheck:
    """A single confidence-scored check point.

    Attributes:
        category: What's being checked (e.g. "register", "baud_rate", "pin").
        identifier: The specific item (e.g. "PORTB", "9600", "pin13").
        score: Confidence score 0-100 (higher = more confident).
        source: Where the check resolved (e.g. "reference", "presets").
        resolved: Whether the item was found in a knowledge source.
        note: Human-readable explanation.
    """

    category: str
    identifier: str
    score: float = 0.0
    source: str = ""
    resolved: bool = False
    note: str = ""

    def needs_review(self, threshold: float = DEFAULT_CONFIDENCE_THRESHOLD) -> bool:
        return self.score < threshold

    def summary(self) -> str:
        status = "OK" if self.score >= DEFAULT_CONFIDENCE_THRESHOLD else "REVIEW"
        return f"[{status}] {self.category}: {self.identifier} ({self.score:.0f}%)"


@dataclass
class ConfidenceReport:
    """Aggregated confidence report for a Code→Build safety gate.

    Attributes:
        checks: Individual confidence checks.
        overall_score: Weighted average of all checks (0-100).
        needs_review: True if overall_score < DEFAULT_CONFIDENCE_THRESHOLD.
        review_items: List of checks that need review.
        source_review_passed: True if source review validation passed.
    """

    checks: list[ConfidenceCheck] = field(default_factory=list)
    overall_score: float = 100.0
    needs_review: bool = False
    review_items: list[ConfidenceCheck] = field(default_factory=list)
    source_review_passed: bool = True

    def summary(self) -> str:
        lines = [
            f"Confidence Report: {self.overall_score:.0f}% {'(NEEDS REVIEW)' if self.needs_review else '(OK)'}",
            f"  Checks: {len(self.checks)}, Review items: {len(self.review_items)}",
            f"  Code Review: {'PASS' if self.source_review_passed else 'FAIL'}",
        ]
        for c in self.review_items:
            lines.append(f"  {c.summary()}")
        return "\n".join(lines)


class ConfidenceScorer:
    """Confidence scoring engine for generated code.

    Args:
        knowledge_base: KnowledgeBase with reference library loaded.
        source_reviewer: SourceReviewer for pre-scoring analysis.
        threshold: Minimum confidence threshold (default 58%, per §2.7).
    """

    def __init__(
        self,
        knowledge_base: KnowledgeBase,
        source_reviewer: SourceReviewer | None = None,
        threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    ) -> None:
        self._knowledge_base = knowledge_base
        self._validator = source_reviewer or SourceReviewer(knowledge_base)
        self._threshold = threshold

    @property
    def knowledge_base(self) -> KnowledgeBase:
        return self._knowledge_base

    def analyze(
        self,
        source_code: str,
        board_config: dict[str, Any] | None = None,
        source_review_result: SourceReviewResult | None = None,
    ) -> ConfidenceReport:
        """Run confidence scoring on source code.

        Args:
            source_code: C/C++ source code to analyze.
            board_config: Board configuration dict (from board.json).
            source_review_result: Pre-computed Source Review result (if available).

        Returns:
            ConfidenceReport with checks and overall score.
        """
        report = ConfidenceReport()

        # Step 1: Run source review validation (if not provided)
        if source_review_result is None:
            source_review_result = self._validator.validate(source_code)
        report.source_review_passed = source_review_result.passed

        # Step 2: Score register assignments
        self._score_registers(source_code, source_review_result, report)

        # Step 3: Score baud rate configurations
        self._score_baud_rate(source_code, board_config, report)

        # Step 4: Score pin assignments
        self._score_pins(source_code, board_config, report)

        # Step 5: Compute overall score
        report.overall_score = self._compute_overall(report)
        report.needs_review = report.overall_score < self._threshold
        report.review_items = [c for c in report.checks if c.needs_review()]

        logger.info("Confidence: %.0f%% (%d checks, %s)",
                     report.overall_score, len(report.checks),
                     "NEEDS_REVIEW" if report.needs_review else "OK")

        return report

    def _score_registers(
        self,
        source_code: str,
        source_review_result: SourceReviewResult,
        report: ConfidenceReport,
    ) -> None:
        """Score register access confidence based on source review results.

        High confidence: register + field both resolved in reference library.
        Medium confidence: register resolved but field unresolved (macro/constant).
        Zero confidence: register not resolved (hallucinated).
        """
        import re

        # For registers found in reference library → high confidence
        for line in source_code.splitlines():
            # Find register assignments: REG =, REG |=, REG &=, etc.
            for match in re.finditer(
                r'\b([A-Z][A-Z0-9_]{2,})\s*(?:\|=|&=|<<=|>>=|^=|\+=|-=|\*=|/=|%=|=)',
                line
            ):
                reg_name = match.group(1)
                if reg_name in {"uint8_t", "uint16_t", "uint32_t", "int", "char"}:
                    continue

                reg = self._knowledge_base.lookup_register(reg_name)
                if reg:
                    report.checks.append(ConfidenceCheck(
                        category="register",
                        identifier=reg_name,
                        score=100.0,
                        source="reference",
                        resolved=True,
                        note=f"Register at {reg['address']}",
                    ))

        # Violations from Source Review → zero confidence for that register
        for v in source_review_result.violations:
            report.checks.append(ConfidenceCheck(
                category="register",
                identifier=v.register,
                score=0.0,
                source="none",
                resolved=False,
                note=f"Hallucinated register: {v.reason}",
            ))

    def _score_baud_rate(
        self,
        source_code: str,
        board_config: dict[str, Any] | None,
        report: ConfidenceReport,
    ) -> None:
        """Score baud rate confidence by checking against presets table.

        Looks for UBRR value patterns and compares to known baud presets.
        """
        import re

        # Look for UBRR assignments: UBRR0L = 103, UBRR0H = 0
        for match in re.finditer(
            r'(UBRR\d[HL])\s*=\s*(\d+)',
            source_code
        ):
            reg_name = match.group(1)  # e.g. UBRR0L
            ubrr_byte = int(match.group(2))

            # For UBRR0L, the UBRR value might be the full 12-bit value
            # For UBRR0H, it's typically 0 for standard baud rates
            if "H" in reg_name and ubrr_byte == 0:
                # UBRR0H=0 is correct for all standard presets (UBRR < 256)
                report.checks.append(ConfidenceCheck(
                    category="baud_rate",
                    identifier=reg_name,
                    score=90.0,
                    source="presets",
                    resolved=True,
                    note="UBRR_H=0 matches all standard presets",
                ))
            elif "L" in reg_name:
                # Find the best matching preset
                best_match = None
                best_diff = float("inf")
                # Resolve board_id for pin map: prefer explicit id, fall back to legacy default
                board_id = (board_config or {}).get("board_id", "")
                if not board_id:
                    # Fallback for backward compat: infer from chip
                    chip = (board_config or {}).get("mcu", {}).get("chip", "")
                    if "328P" in chip or "328" in chip:
                        board_id = "arduino_uno"
                    elif "2560" in chip:
                        board_id = "arduino_mega"
                    else:
                        board_id = "arduino_mega"
                for baud_str, preset in self._knowledge_base.get_pin_map(
                    board_id
                ).get("baud_rate_presets", {}).items():
                    preset_ubrr = preset.get("ubrr", 0)
                    diff = abs(ubrr_byte - preset_ubrr)
                    if diff < best_diff:
                        best_diff = diff
                        best_match = baud_str

                if best_match and best_diff <= 1:
                    # Exact or near-exact match
                    report.checks.append(ConfidenceCheck(
                        category="baud_rate",
                        identifier=reg_name,
                        score=100.0,
                        source="presets",
                        resolved=True,
                        note=f"UBRR matches {best_match} baud preset (diff={best_diff})",
                    ))
                elif best_match and best_diff <= 10:
                    score = max(40, 100 - best_diff * 5)
                    report.checks.append(ConfidenceCheck(
                        category="baud_rate",
                        identifier=reg_name,
                        score=float(score),
                        source="presets",
                        resolved=True,
                        note=f"UBRR close to {best_match} baud (diff={best_diff})",
                    ))
                else:
                    report.checks.append(ConfidenceCheck(
                        category="baud_rate",
                        identifier=reg_name,
                        score=20.0,
                        source="unknown",
                        resolved=False,
                        note=f"UBRR value {ubrr_byte} not in known presets",
                    ))

    def _score_pins(
        self,
        source_code: str,
        board_config: dict[str, Any] | None,
        report: ConfidenceReport,
    ) -> None:
        """Score pin assignment confidence.

        Checks port/bit combinations against the pin mapping table.
        Arduino code uses pinMode/digitalWrite (resolved via API) or
        direct DDRx/PORTx writes (resolved via reference library).

        For direct register access, check if the port exists.
        """
        import re

        # Direct PORT/DDR access patterns
        for match in re.finditer(r'\b(DDR|PORT)([A-L])\b', source_code):
            port_name = match.group(1) + match.group(2)
            reg = self._knowledge_base.lookup_register(port_name)
            if reg:
                report.checks.append(ConfidenceCheck(
                    category="pin",
                    identifier=port_name,
                    score=100.0,
                    source="reference",
                    resolved=True,
                    note=f"Valid GPIO register at {reg['address']}",
                ))

        # Check pin number references (pinMode(13, ...), digitalWrite(13, ...))
        for match in re.finditer(
            r'(?:pinMode|digitalWrite|digitalRead|analogRead|analogWrite)'
            r'\s*\(\s*(\d+)',
            source_code
        ):
            pin_num = int(match.group(1))
            pin = self._knowledge_base.lookup_pin(pin_num)
            if pin:
                report.checks.append(ConfidenceCheck(
                    category="pin",
                    identifier=f"pin{pin_num}",
                    score=100.0,
                    source="reference",
                    resolved=True,
                    note=f"Pin {pin_num} = PORT{pin['port']} bit {pin['bit']}",
                ))
            elif board_config:
                # Check against board.json pins
                board_pins = board_config.get("pins", {})
                if str(pin_num) in board_pins or pin_num in board_pins.values():
                    report.checks.append(ConfidenceCheck(
                        category="pin",
                        identifier=f"pin{pin_num}",
                        score=80.0,
                        source="board.json",
                        resolved=True,
                        note="Resolved via board.json (no AVR mapping)",
                    ))
                else:
                    report.checks.append(ConfidenceCheck(
                        category="pin",
                        identifier=f"pin{pin_num}",
                        score=30.0,
                        source="unknown",
                        resolved=False,
                        note=f"Pin {pin_num} not in reference or board config",
                    ))

    def _compute_overall(self, report: ConfidenceReport) -> float:
        """Compute weighted average confidence score.

        Source Review failures heavily penalize overall confidence.
        """
        if not report.checks:
            return 100.0

        # Source Review failures → strong confidence penalty
        if not report.source_review_passed:
            return min(30.0, sum(c.score for c in report.checks) / len(report.checks))

        # Weighted average: resolved items get full weight, unresolved get half
        total_weight = 0.0
        weighted_sum = 0.0
        for c in report.checks:
            weight = 1.0 if c.resolved else 0.5
            weighted_sum += c.score * weight
            total_weight += weight

        return weighted_sum / total_weight if total_weight > 0 else 100.0
