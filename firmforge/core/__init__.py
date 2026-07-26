"""FirmForge Core — MCU code verification toolchain.

Modules:
- board_detector: USB/COM port scan, board identification, chip probe chain
- pipeline_state: fingerprint-driven incremental pipeline (state.json)
- source_reviewer: register review (Code Review)
- confidence_scorer: baud rate / pin confidence scoring
- experience_ledger: cross-session engineering experience accumulation (reserved)
- pipeline_runner: 5-Stage Pipeline executor (Review → Build → Flash → Test)
"""

from firmforge.core.board_detector import BoardDetector
from firmforge.core.source_reviewer import SourceReviewer
from firmforge.core.confidence_scorer import ConfidenceScorer
from firmforge.core.pipeline_state import PipelineState
from firmforge.core.pipeline_runner import PipelineRunner
from firmforge.core.experience_ledger import ExperienceLedger

__all__ = [
    "BoardDetector",
    "SourceReviewer",
    "ConfidenceScorer",
    "PipelineState",
    "PipelineRunner",
    "ExperienceLedger",
]
