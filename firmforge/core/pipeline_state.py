"""Pipeline state file (.firmforge/state.json) — fingerprint-driven incremental.

Agent repeatedly calls ff verify --app <dir>. This module records what
happened last time (fingerprints of inputs) so we skip stages whose
inputs haven't changed. Agent doesn't need to know about this file.

Fingerprint propagation: if source code changes, Review+Build+Flash+Test
are all invalidated. If hex changes, Flash+Test invalidated.
If COM port changes, Flash+Test invalidated. If board changes, everything.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_STATE_FILE_NAME = "state.json"


def _sha256_hex(path: Path) -> str:
    if not path.exists():
        return ""
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()[:16]


def compute_fingerprints(
    board_id: str,
    port: str,
    source_dir: str | None,
    hex_path: str | None,
) -> dict[str, Any]:
    """Compute input fingerprints for stage-skip decisions."""
    fps: dict[str, str] = {
        "board_id": board_id,
        "port": port,
    }

    # Source fingerprint: all .cpp/.c/.h under source_dir
    if source_dir:
        sd = Path(source_dir)
        if sd.is_dir():
            h = hashlib.sha256()
            for f in sorted(sd.rglob("*")):
                if f.suffix in (".cpp", ".c", ".h", ".ino") and f.is_file():
                    h.update(f.read_bytes())
            fps["source"] = h.hexdigest()[:16]
        else:
            fps["source"] = ""
    else:
        fps["source"] = ""

    # Hex fingerprint
    fps["hex"] = _sha256_hex(Path(hex_path)) if hex_path else ""

    return fps


def fingerprint_match(
    stored: dict[str, Any] | None,
    current: dict[str, Any],
    keys: list[str],
) -> bool:
    """True if all named keys match between stored and current."""
    if not stored:
        return False
    for k in keys:
        if stored.get(k) != current.get(k):
            return False
    return True


class PipelineState:
    """Read/write .firmforge/state.json for incremental pipeline execution."""

    def __init__(self, workspace: Path) -> None:
        self._path = workspace / ".firmforge" / _STATE_FILE_NAME
        self._data: dict[str, Any] = self._load()

    def _load(self) -> dict[str, Any]:
        if self._path.exists():
            try:
                return json.loads(self._path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                logger.debug("State file corrupt, resetting")
        return {}

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._data, indent=2, ensure_ascii=False),
                              encoding="utf-8")

    @property
    def data(self) -> dict[str, Any]:
        return self._data

    def stage_status(self, stage_name: str) -> str:
        return self._data.get("stages", {}).get(stage_name, {}).get("status", "pending")

    def mark_done(self, stage_name: str, **details: Any) -> None:
        entry = self._data.setdefault("stages", {}).setdefault(stage_name, {"status": "done"})
        entry["status"] = "done"
        entry.update(details)  # merge, don't overwrite previous data

    def mark_failed(self, stage_name: str, error: str) -> None:
        self._data.setdefault("last_error", {})["stage"] = stage_name
        self._data["last_error"]["message"] = error
        entry = self._data.setdefault("stages", {}).setdefault(stage_name, {})
        entry["status"] = "failed"
        entry["error"] = error

    def should_skip_build(self, fingerprints: dict[str, Any]) -> bool:
        stored = self._data.get("fingerprints", {})
        return (fingerprint_match(stored, fingerprints, ["board_id", "source"]) and
                bool(fingerprints.get("source")) and
                bool(stored.get("hex")))  # hex is build OUTPUT — check stored, not current

    def should_skip_flash(self, fingerprints: dict[str, Any]) -> bool:
        stored = self._data.get("fingerprints", {})
        return (fingerprint_match(stored, fingerprints, ["board_id", "source", "hex", "port"]) and
                bool(stored.get("hex")))

    def should_skip_test(self, fingerprints: dict[str, Any]) -> bool:
        stored = self._data.get("fingerprints", {})
        return (fingerprint_match(stored, fingerprints, ["board_id", "source", "hex", "port"]) and
                bool(stored.get("hex")))

    def update_fingerprints(self, fingerprints: dict[str, Any]) -> None:
        self._data["fingerprints"] = fingerprints

    def increment_compile_rounds(self) -> int:
        """Record one failed compile attempt. Returns new round count."""
        entry = self._data.setdefault("stages", {}).setdefault("build", {})
        count = entry.get("compile_rounds", 0) + 1
        entry["compile_rounds"] = count
        return count

    def reset_compile_rounds(self) -> None:
        """Reset compile round counter on successful build."""
        entry = self._data.setdefault("stages", {}).get("build", {})
        entry.pop("compile_rounds", None)

    @staticmethod
    def clear(workspace: Path) -> None:
        path = workspace / ".firmforge" / _STATE_FILE_NAME
        if path.exists():
            path.unlink()
