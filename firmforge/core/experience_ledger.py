"""Experience Ledger -- cross-session engineering experience accumulation.

规划 §2.8.1: P0借鉴 from Claude-Agent-MCU.
After each error recovery, auto-extract a Lesson and append to ledger.jsonl.
On next compile/flash, grep similar historical lessons and inject into context.

Sits alongside AgentTrace (short-term, per-session) and provides
long-term, cross-session experience memory.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Lesson:
    """A single engineering lesson extracted from error recovery.

    Each lesson captures: what went wrong, what fixed it,
    and context for future similarity matching.
    """
    error_pattern: str         # key matching field, e.g. "undefined_reference"
    fix_description: str       # human-readable, e.g. "add -lm to linker flags"
    source_file: str = ""      # file where error occurred
    source_line: int = 0
    mcu_platform: str = ""     # arduino
    board_name: str = ""
    tool: str = ""             # avr-gcc | avrdude | openocd
    severity: str = "medium"   # low | medium | high | critical
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    resolution_success: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "error_pattern": self.error_pattern,
            "fix_description": self.fix_description,
            "source_file": self.source_file,
            "source_line": self.source_line,
            "mcu_platform": self.mcu_platform,
            "board_name": self.board_name,
            "tool": self.tool,
            "severity": self.severity,
            "timestamp": self.timestamp,
            "resolution_success": self.resolution_success,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Lesson:
        return cls(
            error_pattern=d.get("error_pattern", ""),
            fix_description=d.get("fix_description", ""),
            source_file=d.get("source_file", ""),
            source_line=d.get("source_line", 0),
            mcu_platform=d.get("mcu_platform", ""),
            board_name=d.get("board_name", ""),
            tool=d.get("tool", ""),
            severity=d.get("severity", "medium"),
            timestamp=d.get("timestamp", ""),
            resolution_success=d.get("resolution_success", True),
        )


class ExperienceLedger:
    """Append-only JSONL ledger for cross-session experience.

    Usage:
        ledger = ExperienceLedger(Path("./ledger.jsonl"))
        ledger.record(Lesson(error_pattern="undefined_reference", ...))

        # Before next compile, inject relevant lessons:
        hints = ledger.search("undefined_reference", platform="arduino", limit=5)
    """

    def __init__(self, ledger_path: Path | str = "ledger.jsonl") -> None:
        self._path = Path(ledger_path)
        self._lessons: list[Lesson] = []
        if self._path.exists():
            self._load()

    # -- Write --

    def record(self, lesson: Lesson) -> None:
        """Append a lesson to the ledger (immediate persistence)."""
        self._lessons.append(lesson)
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(lesson.to_dict(), ensure_ascii=False) + "\n")
        logger.info("Lesson recorded: %s — %s",
                     lesson.error_pattern, lesson.fix_description[:60])

    def record_from_recovery(
        self,
        state: str,
        error_message: str,
        fix_applied: str,
        source_file: str = "",
        platform: str = "",
        board: str = "",
        tool: str = "",
        success: bool = True,
    ) -> Lesson:
        """Convenience: record a lesson from state machine recovery context.

        Called after COMPILE_FIX exhaustion or successful recovery.
        """
        lesson = Lesson(
            error_pattern=self._classify_pattern(state, error_message),
            fix_description=fix_applied,
            source_file=source_file,
            mcu_platform=platform,
            board_name=board,
            tool=tool,
            severity="high" if not success else "medium",
            resolution_success=success,
        )
        self.record(lesson)
        return lesson

    # -- Read / Search --

    def search(
        self,
        error_keyword: str = "",
        platform: str = "",
        board: str = "",
        limit: int = 5,
    ) -> list[Lesson]:
        """Simple keyword + field match search.

        For MVP, use linear scan with case-insensitive keyword match.
        Stage 4+ can upgrade to vector search.

        Returns lessons sorted by recency (most recent first).
        """
        results: list[Lesson] = []
        keyword_lower = error_keyword.lower() if error_keyword else ""

        for lesson in reversed(self._lessons):
            if platform and lesson.mcu_platform != platform:
                continue
            if board and lesson.board_name != board:
                continue
            if keyword_lower:
                # Normalize both sides: underscore ↔ space for fuzzy matching
                pattern_lower = lesson.error_pattern.lower().replace("_", " ")
                desc_lower = lesson.fix_description.lower()
                keyword_norm = keyword_lower.replace("_", " ")
                # Bidirectional match: keyword contains pattern OR pattern contains keyword
                if not (keyword_norm in pattern_lower or
                        pattern_lower in keyword_norm or
                        keyword_norm in desc_lower):
                    continue
            results.append(lesson)
            if len(results) >= limit:
                break

        return results

    def get_hints(
        self,
        error_message: str,
        platform: str = "",
        limit: int = 3,
    ) -> list[str]:
        """Get human-readable hints for LLM error-fix context.

        Searches for similar errors and returns fix descriptions.
        """
        # Normalize: extract meaningful keywords from error message
        # e.g. "undefined reference to 'sin'" → "undefined reference"
        normalized = error_message[:80].replace("_", " ")  # underscore→space for fuzzy match
        lessons = self.search(error_keyword=normalized,
                              platform=platform, limit=limit)
        if not lessons:
            # Fallback: try without platform filter
            lessons = self.search(error_keyword=normalized, limit=limit)
        return [
            f"[{lesson.severity}] {lesson.error_pattern}: {lesson.fix_description}"
            for lesson in lessons if lesson.resolution_success
        ]

    def stats(self) -> dict[str, Any]:
        """Return basic ledger statistics."""
        by_platform: dict[str, int] = {}
        by_pattern: dict[str, int] = {}
        success_count = 0
        for lesson in self._lessons:
            by_platform[lesson.mcu_platform] = by_platform.get(lesson.mcu_platform, 0) + 1
            by_pattern[lesson.error_pattern] = by_pattern.get(lesson.error_pattern, 0) + 1
            if lesson.resolution_success:
                success_count += 1
        return {
            "total_lessons": len(self._lessons),
            "success_rate": (success_count / len(self._lessons)
                             if self._lessons else 0),
            "by_platform": by_platform,
            "top_patterns": sorted(by_pattern.items(),
                                   key=lambda x: x[1], reverse=True)[:5],
        }

    # -- Internals --

    def _load(self) -> None:
        """Load existing lessons from file."""
        with open(self._path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    lesson = Lesson.from_dict(json.loads(line))
                    self._lessons.append(lesson)
                except (json.JSONDecodeError, KeyError) as e:
                    logger.warning("Skipping corrupt ledger line: %s", e)

    @staticmethod
    def _classify_pattern(state: str, error_message: str) -> str:
        """Classify error pattern from a raw error message."""
        msg_lower = error_message.lower()
        if "undefined reference" in msg_lower:
            return "undefined_reference"
        if "error:" in msg_lower or "fatal error" in msg_lower:
            return "compile_error"
        if "stk500" in msg_lower or "programmer" in msg_lower:
            return "flash_error"
        if "timeout" in msg_lower:
            return "timeout"
        if state == "compile_fix":
            return "compile_fix_loop_exhausted"
        return "unknown"
