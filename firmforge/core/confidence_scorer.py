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
class CategoryScore:
    """一个分项的得分 —— 「惩罚局部化」的载体。

    为什么必须有分项：一个数字（尤其是不带解释的 30%）无法区分「10 个寄存器
    错了 2 个」与「整个文件不可信」。前者是局部缺口，后者是代码有问题，处理
    方式完全不同。分项让扣分落在它该落的地方，不再一票打死全局。
    """

    label: str
    checked: int = 0
    resolved: int = 0
    score: float = 100.0
    note: str = ""

    def __str__(self) -> str:
        if not self.checked:
            return f"{self.label} —（本次无此类引用）"
        tail = f"，{self.note}" if self.note else ""
        return (f"{self.label} {self.resolved}/{self.checked} "
                f"({self.score:.0f}%){tail}")


@dataclass
class ConfidenceReport:
    """Aggregated confidence report for a Code→Build safety gate.

    Attributes:
        checks: Individual confidence checks.
        overall_score: 各分项按**检查条数**加权的平均（0-100）。
        needs_review: 总分低于阈值，或**任一分项**低于阈值。
        review_items: List of checks that need review.
        source_review_passed: True if source review validation passed.
        explanation: 分数为什么是这个数。空串 = 没有单项低于阈值。
        category_scores: registers / fields / pins / baud_rate 四类分项。
    """

    checks: list[ConfidenceCheck] = field(default_factory=list)
    overall_score: float = 100.0
    needs_review: bool = False
    review_items: list[ConfidenceCheck] = field(default_factory=list)
    source_review_passed: bool = True
    #: 源审查未通过的具体条目（`file:line 名字`）
    source_review_failures: list[str] = field(default_factory=list)
    #: 分数解释。**不是**"被硬上限压过"，本类不存在硬上限。
    explanation: str = ""
    #: 分项得分。键：registers / fields / pins / baud_rate
    category_scores: dict[str, CategoryScore] = field(default_factory=dict)

    def summary(self) -> str:
        lines = [
            f"Confidence Report: {self.overall_score:.0f}% "
            f"{'(NEEDS REVIEW)' if self.needs_review else '(OK)'}",
            "  " + " · ".join(str(c) for c in self.category_scores.values()),
            f"  Code Review: {'PASS' if self.source_review_passed else 'FAIL'}",
        ]
        if self.explanation:
            lines.append(f"  Why: {self.explanation}")
        for f in self.source_review_failures[:5]:
            lines.append(f"  未解析: {f}")
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
        report.source_review_failures = [
            (f"{_where(v)} {v.register}")
            for v in (source_review_result.violations
                      + source_review_result.allowed)
        ]

        # Step 2: 分项计分。registers / fields 直接用源审查的计数 —— 那是
        # 唯一一份"实际扫过源码"的结果，另起一套正则只会得到两套不一致的数。
        #
        # 知识库缺口（`kb_gaps`）与已声明豁免（`registers_allowed`）都从分母
        # 里剔除：这两类**工具没有判定过**，拿它们扣分等于因为自己没收录、
        # 或因为用户已核对过而判源码有罪 —— 正是用户报的那类误判。
        judged_regs = max(0, source_review_result.registers_checked
                          - source_review_result.kb_gaps
                          - source_review_result.registers_allowed)
        notes = []
        if source_review_result.kb_gaps:
            notes.append(f"{source_review_result.kb_gaps} 条未收录（不判定）")
        if source_review_result.registers_allowed:
            notes.append(f"{source_review_result.registers_allowed} 条已豁免")
        report.category_scores["registers"] = _category_from_review(
            "registers", judged_regs,
            source_review_result.registers_resolved,
            note="，".join(notes))
        report.category_scores["fields"] = _category_from_review(
            "fields", source_review_result.fields_checked,
            source_review_result.fields_resolved)

        # Step 3: 波特率与引脚 —— 这两类各自的 check 自带分数
        self._score_baud_rate(source_code, board_config, report)
        self._score_pins(source_code, board_config, report)
        report.category_scores["baud_rate"] = _category_from_checks(
            report, "baud_rate", "baud_rate")
        report.category_scores["pins"] = _category_from_checks(
            report, "pin", "pins")

        # Step 4: Compute overall score（按检查条数加权，无硬上限）
        report.overall_score = self._compute_overall(report)

        # Step 5: 哪个分项低于阈值 —— 只有这一层能说清"为什么低"
        lows = [c for c in report.category_scores.values()
                if c.checked and c.score < self._threshold]
        if lows:
            report.explanation = "低于阈值的分项：" + "；".join(
                f"{c.label} {c.score:.0f}%（{c.resolved}/{c.checked} 条）"
                for c in lows)
            for c in lows:
                report.review_items.append(ConfidenceCheck(
                    category=c.label, identifier=f"{c.resolved}/{c.checked}",
                    score=c.score, source="review", resolved=False,
                    note=c.note or "未解析条目见 S2 的 [review] 明细"))
        elif report.overall_score < self._threshold:
            report.explanation = (
                "没有单一分项低于阈值，是多项中等偏低累积的结果"
                "（分项见上）")

        report.needs_review = bool(lows) or report.overall_score < self._threshold

        logger.debug("Confidence: %.0f%% (%s)", report.overall_score,
                    "NEEDS_REVIEW" if report.needs_review else "OK")
        if report.explanation:
            logger.debug("Confidence 分项原因: %s", report.explanation)

        return report

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
                        board_id = "arduino_328p"
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

        # 引脚号查询（pinMode(13, ...) / digitalWrite(13, ...)）。
        #
        # 这里**不再重复统计** `DDRB = ...` / `PORTB = ...` 这类直接寄存器
        # 访问：它们已经在 registers 分项里按同一个 lookup_register 查过一遍
        # 了。同一处引用计两次，会让「一个寄存器写错」在总分里被算两遍，
        # 也会让 pins 分项的条数虚高。
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
                    note=f"Pin {pin_num} = {pin.get('register') or 'PORT' + pin['port']} bit {pin['bit']}",
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
        """各分项按**检查条数**加权的平均。

        **没有硬上限。** 旧实现里只要源审查有任何一个 error，总分就被
        ``min(30, avg)`` 压到 30% —— 一个文件里错一个寄存器名字，整个工程
        的置信度都是 30%，这个数字既不可解释也不能指导任何动作。加到
        ``cap_reason`` 里解释「为什么是 30」只是在给错误的设计写说明书。

        现在扣分只落在出错的那个分项上：10 个寄存器错 2 个 → registers 80%，
        pins / baud 不受影响；总分按条数加权后自然反映错误密度。
        """
        scored = [c for c in report.category_scores.values() if c.checked]
        if not scored:
            return 100.0
        total_checked = sum(c.checked for c in scored)
        if total_checked <= 0:
            return 100.0
        return sum(c.score * c.checked for c in scored) / total_checked


# ---------------------------------------------------------------------------
# 分项构建
# ---------------------------------------------------------------------------


def _category_from_review(label: str, checked: int, resolved: int,
                           note: str = "") -> CategoryScore:
    """用源审查的计数造一个分项。

    这里**不另起一套正则**重扫源码 —— 那样会得到两套互不一致的数（源审查
    报了 9 个寄存器、置信度算出 10 个），而调用方无法判断该信哪个。
    """
    if not checked:
        return CategoryScore(label, 0, 0, 100.0, note)
    return CategoryScore(label, checked, resolved,
                         100.0 * resolved / checked, note)


def _category_from_checks(report: ConfidenceReport, key: str,
                           label: str) -> CategoryScore:
    """把一个类别的逐条 check 汇总成分项得分。"""
    items = [c for c in report.checks if c.category == key]
    if not items:
        return CategoryScore(label)
    score = sum(c.score for c in items) / len(items)
    resolved = sum(1 for c in items if c.resolved)
    return CategoryScore(label, len(items), resolved, score)


def _where(item: Any) -> str:
    """``file:line`` 落点。"""
    file = getattr(item, "file", "")
    line = getattr(item, "line", 0)
    if file and line:
        return f"{file}:{line}"
    return f"line {line}" if line else "<unknown>"
