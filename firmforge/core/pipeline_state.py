"""Pipeline state file (`.ff-run/state.json`) — fingerprint-driven incremental.

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

from firmforge.infrastructure import paths

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
    """Read/write `.ff-run/state.json` for incremental pipeline execution.

    `<workspace>/.ff-run/` is the A 区 runtime directory (标准 §4 `runtime` 类）：
    删除它不影响功能，只会丢失增量缓存。
    """

    def __init__(self, workspace: Path) -> None:
        self._path = paths.runtime_dir(workspace) / _STATE_FILE_NAME
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
        # 上一次失败留下的 error 必须清掉，否则 state.json 里会出现
        # 「status=done 且 error=Flash failed」这种自相矛盾的记录，
        # 排查时会被当成真错误（实测踩过一次）。
        entry.pop("error", None)
        entry.update(details)  # merge, don't overwrite previous data

    def mark_failed(self, stage_name: str, error: str) -> None:
        self._data.setdefault("last_error", {})["stage"] = stage_name
        self._data["last_error"]["message"] = error
        entry = self._data.setdefault("stages", {}).setdefault(stage_name, {})
        entry["status"] = "failed"
        entry["error"] = error

    def should_skip_build(self, fingerprints: dict[str, Any]) -> bool:
        """跳过 S3 需要**同时**满足：指纹没变 + 上次那份 hex 还在磁盘上。

        只比指纹是不够的：``cache/build/<board>/<app>/`` 是派生物，允许整块删掉
        （分区标准里就是这么定义的）。删完之后 state.json 仍记着指纹一致，
        于是 S3 显示 ``[skipped] source unchanged, hex exists`` 并报 BUILD PASSED，
        而产物根本不存在 —— 2026-10-28 实测踩到：汇总行紧跟着打印
        ``!! 产物不存在``，两句话自相矛盾，退出码还是 0。

        产物不在了就**重编**，这是唯一诚实的动作：跳过等于对外宣布「有可烧的
        固件」，而下一步 ``ff flash`` 会因此失败或者烧到别的东西上。

        注意取路径的位置：``fingerprints.hex`` 是**固件内容的哈希**，
        产物路径在 ``stages.build.hex`` —— 两者同名不同物，读错了会得到
        一个「看起来像路径的 16 进制串」，``is_file()`` 永远 False。

        还要**核对产出它的板卡**：state 一个工作区只有一份，产物却是按板卡
        分目录放的。同一个工作区编过 A 板再跑 B 板，只查「文件存在」会让 B 板
        复用 A 板的 hex —— 2026-10-28 实测：STM32 的 ff run 跳过 S3 后拿 AVR 的
        5340 B hex 去烧，OpenOCD 报 checksum mismatch 才没写进 Flash。
        旧 state 没有这个字段，一律按「不匹配」处理（重编一次，代价可接受）。
        """
        stored = self._data.get("fingerprints", {})
        build = self._data.get("stages", {}).get("build", {}) or {}
        built_path = str(build.get("hex") or "")
        built_board = str(build.get("board_id") or "")
        want_board = str(fingerprints.get("board_id") or "")
        return (fingerprint_match(stored, fingerprints, ["board_id", "source"]) and
                bool(fingerprints.get("source")) and
                bool(built_path) and built_board != "" and built_board == want_board and
                Path(built_path).is_file())

    def should_skip_flash(self, fingerprints: dict[str, Any]) -> bool:
        stored = self._data.get("fingerprints", {})
        return (fingerprint_match(stored, fingerprints, ["board_id", "source", "hex", "port"]) and
                bool(stored.get("hex")))

    def should_skip_test(self, fingerprints: dict[str, Any]) -> bool:
        # 上一次 S5 必须真的通过过（mark_done 写的 done）。
        # 只看指纹会把「上次验证失败」也算成可跳过：空串口/断言不命中之后，
        # 下一次同输入的调用会显示 [skipped] + overall_success=True，失败被粘成通过。
        if self.stage_status("test") != "done":
            return False
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
        path = paths.runtime_dir(workspace) / _STATE_FILE_NAME
        if path.exists():
            path.unlink()
