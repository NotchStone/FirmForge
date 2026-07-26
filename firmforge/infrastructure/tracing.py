"""Tracing logger -- lightweight JSONL tracing for agent execution.

规划 §2.6: Infrastructure layer, JSONL local file for agent trace/debug.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class TracingLogger:
    """Lightweight JSONL tracing logger.

    Usage:
        tracer = TracingLogger(Path("./traces"))
        tracer.trace("state_transition", {"from": "normal", "to": "compile_fix"})
    """

    def __init__(self, trace_dir: Path | str = "./traces") -> None:
        self._dir = Path(trace_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._file = self._dir / f"trace_{int(time.time())}.jsonl"

    def trace(self, event_type: str, data: dict[str, Any]) -> None:
        """Append a trace event."""
        entry = {
            "ts": time.time(),
            "event": event_type,
            **data,
        }
        with open(self._file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def trace_error(self, error_type: str, message: str,
                    context: dict[str, Any] | None = None) -> None:
        """Trace an error event."""
        data = {"error_type": error_type, "message": message}
        if context:
            data["context"] = context
        self.trace("error", data)

    def trace_state(self, from_state: str, to_state: str, scope: str = "",
                    reason: str = "") -> None:
        """Trace a state machine transition."""
        self.trace("state_transition", {
            "from": from_state,
            "to": to_state,
            "scope": scope,
            "reason": reason,
        })

    def trace_module_step(self, module_name: str, step: str,
                          success: bool, elapsed_ms: float = 0) -> None:
        """Trace a module pipeline step ."""
        self.trace("module_step", {
            "module": module_name,
            "step": step,
            "success": success,
            "elapsed_ms": elapsed_ms,
        })
