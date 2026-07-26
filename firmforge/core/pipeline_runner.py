"""Pipeline Runner — 5-Stage verification pipeline.

Stages: Detect (auto) → Review → Build → Flash → Test

Detect is automatic — always runs first to identify board/port.
State.json fingerprints drive incremental skip decisions.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from firmforge.core.experience_ledger import ExperienceLedger
from firmforge.core.board_detector import BoardDetector
from firmforge.core.source_reviewer import SourceReviewer, SourceReviewResult
from firmforge.core.confidence_scorer import ConfidenceScorer, ConfidenceReport
from firmforge.core.pipeline_state import PipelineState, compute_fingerprints

logger = logging.getLogger(__name__)


@dataclass
class PipelineStage:
    """Result of a single pipeline stage."""
    stage: int
    name: str
    success: bool = False
    elapsed_ms: float = 0.0
    details: dict[str, Any] = field(default_factory=dict)
    error: str = ""


@dataclass
class PipelineResult:
    """Aggregated pipeline execution result."""
    stages: list[PipelineStage] = field(default_factory=list)
    overall_success: bool = False
    board: str = ""
    total_elapsed_ms: float = 0.0


class PipelineRunner:
    """Executes the 5-Stage verification pipeline.

    Usage:
        runner = PipelineRunner(boards_dir="./boards")
        result = runner.run_full(source_dir="boards/arduino_328p/apps/blink")
    """

    def __init__(
        self,
        boards_dir: str | Path = "./boards",
        workspace: str | Path = ".",
    ) -> None:
        self._boards_dir = Path(boards_dir)
        self._workspace = Path(workspace)
        self._ledger = ExperienceLedger(Path(workspace) / ".firmforge" / "ledger.jsonl")
        self._detector = BoardDetector(boards_dir=self._boards_dir)
        self._source_reviewer: SourceReviewer | None = None
        self._sr_chip: str | None = None  # chip of the cached source_reviewer
        self._confidence_scorer: ConfidenceScorer | None = None

    def _skipped_stage(self, stage_num: int, name: str, reason: str = "") -> PipelineStage:
        stage = PipelineStage(stage=stage_num, name=name)
        stage.success = True
        stage.elapsed_ms = 0
        stage.details = {"skipped": True, "reason": reason}
        return stage

    # ===================================================================
    # Public API
    # ===================================================================

    def detect(self) -> dict[str, Any]:
        """Scan for connected boards and return detection results.

        Returns dict with board_id, candidates, port for direct Agent consumption.
        """
        detector = self._detector
        result = detector.detect()
        boards = result.boards if result.boards else []
        candidates = result.candidates if result.candidates else []

        return {
            "board_id": result.board_id,
            "boards": boards,
            "candidates": [
                {"board_id": c.board_id, "confidence": c.confidence,
                 "source": c.source, "details": c.details}
                for c in candidates
            ],
            "detected": bool(result.board_id),
        }

    def build(self, source_dir: str, board_id: str | None = None) -> PipelineResult:
        """Run Detect + Review + Build only (no Flash/Test)."""
        return self.run_full(source_dir=source_dir, board_id=board_id,
                            stop_after="build")

    def flash(self, board_id: str | None = None,
              firmware_path: str = "") -> PipelineResult:
        """Flash pre-compiled hex only (no Review/Build)."""
        result = PipelineResult()
        start = time.time()

        s1 = self._stage_detect(board_id)
        result.stages.append(s1)
        if not s1.success:
            result.total_elapsed_ms = (time.time() - start) * 1000
            return result

        board_id = s1.details.get("board_id", board_id)
        result.board = board_id or "unknown"

        s4 = self._stage_flash(board_id, firmware_path)
        result.stages.append(s4)

        result.overall_success = s4.success
        result.total_elapsed_ms = (time.time() - start) * 1000
        return result

    def verify(self,
               source_dir: str,
               board_id: str | None = None,
               expected: str = "") -> PipelineResult:
        """Run the full 5-stage verification pipeline.

        Args:
            source_dir: Directory containing source code (main.cpp).
            board_id: Board ID. Auto-detected if None.
            expected: Optional serial output pattern for Test stage.
        """
        return self.run_full(source_dir=source_dir, board_id=board_id, expected=expected)

    def run_full(
        self,
        source_dir: str | None = None,
        board_id: str | None = None,
        expected: str = "",
        stop_after: str = "",
        progress_callback: Callable[[str, bool, dict, str | None], None] | None = None,
    ) -> PipelineResult:
        """Execute the 5-Stage Pipeline.

        Detect (auto) → Review → Build → Flash → Test
        Set stop_after="build" to stop after Build stage.

        progress_callback(stage_name, success, details, error):
            Called after each stage completes for real-time progress reporting.
        """
        result = PipelineResult()
        start = time.time()
        state = PipelineState(self._workspace)

        # -- Stage 1: Detect (auto, always runs) --
        s1 = self._stage_detect(board_id)
        result.stages.append(s1)
        self._notify_progress(progress_callback, s1)
        if not s1.success:
            state.mark_failed("detect", s1.error or "Board detection failed")
            state.save()
            result.total_elapsed_ms = (time.time() - start) * 1000
            return result

        board_id = s1.details.get("board_id", board_id)
        result.board = board_id or "unknown"

        # Detect port for fingerprint tracking
        detected_port = ""
        board_config = s1.details.get("config", {})
        try:
            from firmforge.providers import get_flash_provider
            flasher = get_flash_provider(board_config.get("platform", "arduino"), board_config)
            detected_port = flasher.detect_port() or ""
        except Exception:
            pass
        state.mark_done("detect", board_id=board_id)

        if not source_dir:
            result.total_elapsed_ms = (time.time() - start) * 1000
            return result

        # -- Stage 2: Review (Code Review + Confidence Scoring) --
        s2 = self._stage_review(board_id, source_dir, s1.details.get("config", {}))
        result.stages.append(s2)
        self._notify_progress(progress_callback, s2)
        if not s2.success:
            state.mark_failed("review", s2.error or "Review failed")
            state.save()
            result.total_elapsed_ms = (time.time() - start) * 1000
            return result

        state.mark_done("review")

        # Compute source fingerprint
        build_source = source_dir
        fps = compute_fingerprints(
            board_id or "", detected_port, build_source, None,
        )

        # -- Stage 3: Build --
        if state.should_skip_build(fps):
            s3 = self._skipped_stage(3, "Build", "source unchanged, hex exists")
        else:
            s3 = self._stage_build(board_id, build_source)
        result.stages.append(s3)
        self._notify_progress(progress_callback, s3)
        if not s3.success:
            rounds = state.increment_compile_rounds()
            s3.details["compile_rounds"] = rounds
            state.mark_failed("build", s3.error or "Build failed")
            state.save()
            result.total_elapsed_ms = (time.time() - start) * 1000
            return result

        state.reset_compile_rounds()

        if s3.details.get("skipped"):
            fw_path = state.data.get("stages", {}).get("build", {}).get("hex", "")
        else:
            fw_path = s3.details.get("firmware_path", "")
            state.mark_done("build", hex=fw_path)

        fps = compute_fingerprints(
            board_id or "", detected_port, build_source, fw_path,
        )
        state.update_fingerprints(fps)
        state.save()

        if stop_after == "build":
            result.overall_success = all(s.success for s in result.stages)
            result.total_elapsed_ms = (time.time() - start) * 1000
            return result

        # -- Stage 4: Flash --
        build_skipped = s3.details.get("skipped", False)
        flash_done_before = state.data.get("stages", {}).get("flash", {}).get("status") == "done"
        if flash_done_before and (state.should_skip_flash(fps) or build_skipped):
            s4 = self._skipped_stage(4, "Flash",
                "fingerprints match" if state.should_skip_flash(fps) else "Build skipped, flash previously done")
        else:
            s4 = self._stage_flash(board_id, fw_path)
        result.stages.append(s4)
        self._notify_progress(progress_callback, s4)
        if not s4.success:
            state.mark_failed("flash", s4.error or "Flash failed")
            state.save()
            result.total_elapsed_ms = (time.time() - start) * 1000
            return result

        state.mark_done("flash")

        # -- Stage 5: Test --
        # Always run Test if expected pattern is provided (need to verify output)
        if not expected and flash_done_before and (state.should_skip_test(fps) or s4.details.get("skipped")):
            s5 = self._skipped_stage(5, "Test", "fingerprints match")
        else:
            s5 = self._stage_test(board_id, expected)
        result.stages.append(s5)
        self._notify_progress(progress_callback, s5)
        if not s5.success:
            logger.info("S5 Test: FAIL")

        state.mark_done("test")
        state.save()

        # Write serial output summary HTML for Agent panel display
        self._write_serial_summary(source_dir, s5)

        result.overall_success = all(s.success for s in result.stages)
        result.total_elapsed_ms = (time.time() - start) * 1000
        return result

    @staticmethod
    def _notify_progress(
        callback: Callable[[str, bool, dict, str | None], None] | None,
        stage: PipelineStage,
    ) -> None:
        """Fire progress callback if registered."""
        if callback is None:
            return
        try:
            callback(
                stage.name,
                stage.success,
                stage.details or {},
                stage.error,
            )
        except Exception:
            pass  # never let a callback crash the pipeline

    def _write_serial_summary(self, source_dir: str | None, s5: PipelineStage):
        """Write serial_live.html static snapshot after ff_verify."""
        if not source_dir:
            return
        output = s5.details.get("serial_output", "") if s5.details else ""
        baud = s5.details.get("matched_baud", 0) if s5.details else 0
        port = s5.details.get("port", "?") if s5.details else "?"
        html_path = Path(self._workspace) / ".firmforge" / "serial_live.html"
        html_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            html_path.write_text(self._build_serial_html(output, baud, port, source_dir), encoding="utf-8")
        except Exception:
            pass

    @staticmethod
    def _build_serial_html(output: str, baud: int, port: str,
                           source_dir: str) -> str:
        lines = output.splitlines() if output.strip() else ["(no serial data)"]
        rows = ""
        for line in lines[:100]:
            safe = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            rows += f'<div class="line">{safe}</div>\n'

        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<meta http-equiv="refresh" content="2">
<title>FirmForge Serial Output</title>
<style>
:root{{--bg:#1a1a2e;--panel:#16213e;--text:#e0e0e0;--accent:#00d4aa;--dim:#666;--border:#2a2a4a}}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:var(--bg);color:var(--text);font-family:'Cascadia Code','Fira Code','Consolas',monospace;font-size:13px;height:100vh;display:flex;flex-direction:column}}
.header{{background:var(--panel);padding:8px 16px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center;flex-shrink:0}}
.header span{{font-size:12px;color:var(--dim)}}
.header .port{{color:var(--accent)}}
.output{{flex:1;overflow-y:auto;padding:10px 16px;line-height:1.6}}
.output .line{{padding:2px 0;border-bottom:1px solid rgba(255,255,255,0.03);white-space:pre-wrap;word-break:break-all}}
.footer{{background:var(--panel);padding:5px 16px;border-top:1px solid var(--border);font-size:11px;color:var(--dim);text-align:center}}
@media(prefers-color-scheme:light){{:root{{--bg:#f5f5f5;--panel:#e8e8e8;--text:#333;--dim:#888;--border:#ddd;--accent:#007bff}}}}
</style></head>
<body>
<div class="header">
  <span>Serial Monitor <span class="port">{port} @ {baud} baud</span></span>
  <span>{source_dir or "ff_verify"}</span>
</div>
<div class="output">
  {rows}
</div>
<div class="footer">
  Captured during S5 Test stage | reload page for latest snapshot
</div>
</body>
</html>"""

    # ===================================================================
    # Stage 1: Detect
    # ===================================================================

    def _stage_detect(self, board_id: str | None) -> PipelineStage:
        stage = PipelineStage(stage=1, name="Detect")
        t0 = time.time()

        detector = self._detector

        if board_id:
            config = detector.resolve_board(board_id, boards_dir=self._boards_dir)
            if not config:
                stage.success = False
                stage.error = f"board definition not found for {board_id}"
                stage.elapsed_ms = (time.time() - t0) * 1000
                return stage
        else:
            result = detector.detect()
            if result.board_id:
                board_id = result.board_id
                config = detector.resolve_board(board_id, boards_dir=self._boards_dir)
            elif result.boards:
                # Multiple boards detected — list candidates
                stage.success = False
                boards_str = ", ".join(result.boards[:5])
                stage.error = f"Multiple boards detected: {boards_str}. Specify --board <id>"
                stage.elapsed_ms = (time.time() - t0) * 1000
                stage.details["candidates"] = [
                    c.board_id for c in (result.candidates or [])
                ]
                return stage
            else:
                available = detector.list_available_boards()
                if len(available) == 1:
                    board_id = available[0]
                    config = detector.resolve_board(board_id, boards_dir=self._boards_dir)
                else:
                    stage.success = False
                    stage.error = "Cannot determine board — specify via --board <id>"
                    stage.details["available_boards"] = available
                    stage.elapsed_ms = (time.time() - t0) * 1000
                    return stage

        if not config:
            stage.success = False
            stage.error = f"board.json not found for {board_id}"
            stage.elapsed_ms = (time.time() - t0) * 1000
            return stage

        # Inject board_id into config for downstream consumers
        config["board_id"] = board_id

        stage.success = True
        stage.details = {"board_id": board_id, "config": config}
        stage.elapsed_ms = (time.time() - t0) * 1000
        logger.info("S1 Detect: %s", board_id)
        return stage

    # ===================================================================
    # Stage 2: Review
    # ===================================================================

    def _stage_review(self, board_id: str | None, source_dir: str,
                      board_config: dict) -> PipelineStage:
        stage = PipelineStage(stage=2, name="Review")
        t0 = time.time()

        # Phase 1: Cppcheck static analysis (logic bugs, uninit vars, etc.)
        cppcheck_warnings: list[dict] = []
        try:
            from firmforge.providers.arduino.cppcheck import run_cppcheck
            cppcheck_warnings = run_cppcheck(source_dir)
            if cppcheck_warnings:
                logger.info("Cppcheck: %d potential issues found", len(cppcheck_warnings))
        except FileNotFoundError:
            logger.debug("Cppcheck not installed, skipping static analysis")
        except Exception as e:
            logger.debug("Cppcheck skipped: %s", e)

        # Phase 2: Register review (hallucinated register detection)
        c_result = self._review_check(board_id, source_dir, board_config)
        review_ok = not c_result or c_result.passed

        # Phase 3: Confidence Scoring
        conf_result = self._confidence_check(board_id, source_dir, c_result, board_config)
        conf_ok = not (conf_result and conf_result.needs_review)

        sub_stages = [
            {"name": "cppcheck", "success": True,
             "issues": len(cppcheck_warnings)},
            {"name": "review", "success": review_ok,
             "violations": len(c_result.violations) if c_result else 0,
             "registers": [v.register for v in c_result.violations[:10]] if c_result else []},
            {"name": "confidence", "success": conf_ok,
             "score": conf_result.overall_score if conf_result else 100,
             "review_items": len(conf_result.review_items) if conf_result else 0},
        ]

        # Build review details — always include cppcheck results
        details: dict[str, Any] = {
            "sub_stages": sub_stages,
            "cppcheck": cppcheck_warnings,
        }
        if c_result:
            details["warnings"] = [
                {"register": v.register, "line": v.line,
                 "text": v.line_text.strip()[:80],
                 "reason": v.reason}
                for v in (c_result.violations + c_result.warnings)[:20]
            ]

        if not review_ok:
            logger.warning("Code Review WARNING: %d potential register issues (not blocking)",
                           len(c_result.violations))
        elif not conf_ok:
            logger.warning("Confidence below threshold: %.0f%% — needs review",
                           conf_result.overall_score)

        stage.success = True     # S2 is always non-blocking
        stage.details = details

        stage.elapsed_ms = (time.time() - t0) * 1000
        logger.info("S2 Review: PASS (cppcheck=%d, register=%d)",
                     len(cppcheck_warnings),
                     len(c_result.violations) if c_result else 0)
        return stage

    # ===================================================================
    # Code Review & Confidence Scoring (shared helpers)
    # ===================================================================

    @staticmethod
    def _get_confidence_threshold() -> float:
        """Read confidence threshold from platform_config, fallback 58.0."""
        try:
            import yaml
            config_path = Path(__file__).resolve().parent.parent / "infrastructure" / "platform_config.yaml"
            with open(config_path) as f:
                cfg = yaml.safe_load(f)
            return float(cfg.get("arduino", {}).get("confidence_threshold", 58.0))
        except Exception:
            return 58.0

    def _resolve_chip(self, board_id: str | None) -> str:
        """Resolve chip name from board_id -> board.json -> mcu.chip."""
        if board_id:
            try:
                detector = self._detector
                config = detector.resolve_board(board_id, boards_dir=self._boards_dir)
                if config and config.get("mcu", {}).get("chip"):
                    return config["mcu"]["chip"].lower()
            except Exception:
                pass
        return self._default_chip()

    def _get_source_reviewer(self, board_id: str | None = None) -> SourceReviewer:
        chip = self._resolve_chip(board_id)
        if self._sr_chip != chip or self._source_reviewer is None:
            self._load_knowledge_base(chip)
            self._source_reviewer = SourceReviewer(self._knowledge_base)
            self._sr_chip = chip
            logger.info("SourceReviewer init for chip=%s", chip)
        return self._source_reviewer

    def _load_knowledge_base(self, chip: str) -> None:
        """Load KnowledgeBase for the given chip, caching on self._knowledge_base."""
        if getattr(self, "_knowledge_base_chip", None) != chip or not hasattr(self, "_knowledge_base"):
            from firmforge.knowledge.knowledge_base import KnowledgeBase
            self._knowledge_base = KnowledgeBase()
            self._knowledge_base.load_reference("avr", chip=chip)
            self._knowledge_base_chip = chip

    def _review_check(self, board_id: str | None, source_dir: str | None,
                        board_config: dict) -> SourceReviewResult | None:
        if not source_dir:
            return None

        # Arduino API code: skip register-level review.
        # The avr-gcc C++ type system covers all API call validation.
        # Only bare-register C/C++ benefits from hallucinated-register checks.
        source_path = Path(source_dir)
        for f in source_path.rglob("*"):
            if f.suffix == ".ino" and f.is_file():
                logger.info("Arduino sketch detected, skipping register review")
                return None
            if f.suffix in (".c", ".cpp", ".h") and f.is_file():
                try:
                    content = f.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    continue
                if "#include" in content and "Arduino.h" in content:
                    logger.info("Arduino API code detected, skipping register review")
                    return None

        try:
            validator = self._get_source_reviewer(board_id)
            if not source_path.is_dir():
                return None
            # Aggregate results across all source files
            aggregated = SourceReviewResult()
            for f in sorted(source_path.rglob("*")):
                if f.suffix in (".c", ".cpp", ".h", ".ino") and f.is_file():
                    result = validator.validate_file(str(f))
                    aggregated.violations.extend(result.violations)
                    aggregated.warnings.extend(result.warnings)
                    aggregated.registers_checked += result.registers_checked
                    aggregated.registers_resolved += result.registers_resolved
                    aggregated.fields_checked += result.fields_checked
                    aggregated.fields_resolved += result.fields_resolved
                    if not result.passed:
                        aggregated.passed = False
            return aggregated
        except (IOError, OSError, ImportError) as e:
            logger.warning("Source review skipped: %s", e)
            return None

    def _confidence_check(self, board_id: str | None, source_dir: str | None,
                          c_result: SourceReviewResult | None,
                          board_config: dict | None = None) -> ConfidenceReport | None:
        if not source_dir:
            return None
        try:
            if self._confidence_scorer is None:
                chip = self._resolve_chip(board_id)
                self._load_knowledge_base(chip)
                threshold = self._get_confidence_threshold()
                self._confidence_scorer = ConfidenceScorer(self._knowledge_base, threshold=threshold)
            source_path = Path(source_dir)
            if not source_path.is_dir():
                return None
            source_files = (sorted(source_path.glob("*.c*")) + sorted(source_path.glob("*.h"))
                            + sorted(source_path.glob("*.ino")))
            source_code = "\n".join(
                f.read_text(encoding="utf-8", errors="replace")
                for f in source_files if f.is_file()
            )
            if not source_code.strip():
                return None
            # Enrich board_config with board_id for knowledge_base pin lookup
            enriched_config = dict(board_config or {})
            if board_id:
                enriched_config["board_id"] = board_id
                if "aliases" in enriched_config:
                    for alias in enriched_config.get("aliases", []):
                        enriched_config[f"board_alias_{alias}"] = board_id
            return self._confidence_scorer.analyze(
                source_code, board_config=enriched_config, source_review_result=c_result,
            )
        except (IOError, OSError, ImportError) as e:
            logger.warning("Confidence check skipped: %s", e)
            return None

    # ===================================================================
    # Stage 3: Build
    # ===================================================================

    def _stage_build(self, board_id: str | None, source_dir: str | None) -> PipelineStage:
        stage = PipelineStage(stage=3, name="Build")
        t0 = time.time()

        if not source_dir:
            stage.success = False
            stage.error = "No source directory for build"
            stage.elapsed_ms = (time.time() - t0) * 1000
            return stage

        try:
            from firmforge.providers import get_build_provider
            detector = self._detector
            config = detector.resolve_board(board_id or "", boards_dir=self._boards_dir)
            if not config:
                stage.success = False
                stage.error = "Board config not found"
                stage.elapsed_ms = (time.time() - t0) * 1000
                return stage

            builder = get_build_provider(config.get("platform", "arduino"), config)
            # Output builds to ~/.firmforge/cache/build/<board>/<app>/
            # Never pollute source directories with build artifacts.
            from pathlib import Path
            cache_root = Path.home() / ".firmforge" / "cache"
            app_name = Path(source_dir).name
            output_dir = str(cache_root / "build" / (board_id or "unknown") / app_name)
            build_result = builder.build(source_dir, output_dir=output_dir)

            stage.success = build_result.success
            stage.details = {
                "firmware_path": build_result.firmware_path,
                "elapsed_build_ms": build_result.elapsed_ms,
                "errors": [{"msg": e.message} for e in build_result.errors],
            }

            if not build_result.success:
                stage.error = build_result.stderr[-500:] if build_result.stderr else "Build failed (no error output)"
                self._handle_build_error(build_result, source_dir, board_id or "")

        except ImportError as e:
            stage.success = False
            stage.error = f"BuildProvider not available: {e}"

        stage.elapsed_ms = (time.time() - t0) * 1000
        logger.info("S3 Build: %s", "PASS" if stage.success else "FAIL")
        return stage

    # ===================================================================
    # Stage 4: Flash
    # ===================================================================

    def _stage_flash(self, board_id: str | None, firmware_path: str) -> PipelineStage:
        stage = PipelineStage(stage=4, name="Flash")
        t0 = time.time()

        if not firmware_path or not Path(firmware_path).exists():
            stage.success = False
            stage.error = f"Firmware not found: {firmware_path}"
            stage.elapsed_ms = (time.time() - t0) * 1000
            return stage

        try:
            from firmforge.providers import get_flash_provider
            detector = self._detector
            config = detector.resolve_board(board_id or "", boards_dir=self._boards_dir)
            if not config:
                stage.success = False
                stage.error = "Board config not found"
                stage.elapsed_ms = (time.time() - t0) * 1000
                return stage

            flasher = get_flash_provider(config.get("platform", "arduino"), config)
            flash_result = flasher.flash(firmware_path)

            stage.success = flash_result.success
            stage.details = {
                "bytes_written": flash_result.bytes_written if hasattr(flash_result, "bytes_written") else 0,
                "elapsed_flash_ms": flash_result.elapsed_ms if hasattr(flash_result, "elapsed_ms") else 0,
            }
            if not flash_result.success:
                stage.error = flash_result.stderr[-200:] if hasattr(flash_result, "stderr") else "Flash failed"

        except ImportError as e:
            stage.success = False
            stage.error = f"FlashProvider not available: {e}"

        stage.elapsed_ms = (time.time() - t0) * 1000
        logger.info("S4 Flash: %s", "PASS" if stage.success else "FAIL")
        return stage

    # ===================================================================
    # Stage 5: Test
    # ===================================================================

    def _stage_test(self, board_id: str | None, expected: str = "") -> PipelineStage:
        stage = PipelineStage(stage=5, name="Test")
        t0 = time.time()

        try:
            from firmforge.providers import get_flash_provider
            detector = self._detector
            config = detector.resolve_board(board_id or "", boards_dir=self._boards_dir)
            if not config:
                stage.success = True  # Non-blocking
                stage.details = {"note": "Test skipped: no board config"}
                stage.elapsed_ms = (time.time() - t0) * 1000
                return stage

            flasher = get_flash_provider(config.get("platform", "arduino"), config)
            port = flasher.detect_port()
            if not port:
                stage.success = True
                stage.details = {"note": "Test skipped: no COM port"}
                stage.elapsed_ms = (time.time() - t0) * 1000
                return stage

            from firmforge.providers import ComPort
            import re
            _BAUD_RATES = [9600, 115200, 57600, 38400, 19200]
            _MAX_TIMEOUT = 5.0     # max 5s for very slow programs
            _MIN_LINES = 2         # exit early once we have ≥2 complete lines
            matched_baud = 0
            output = ""

            for baud in _BAUD_RATES:
                try:
                    with ComPort(port, baud, timeout=0.3) as ser:
                        import time as _time
                        _time.sleep(0.5)  # wait for MCU to stabilize after DTR
                        try:
                            ser.reset_input_buffer()  # flush stale serial data
                        except Exception:
                            pass
                        deadline = _time.time() + _MAX_TIMEOUT
                        buf = ""
                        while _time.time() < deadline:
                            chunk = ser.read(64)
                            if chunk:
                                if isinstance(chunk, bytes):
                                    chunk = chunk.decode("ascii", errors="replace")
                                buf += chunk
                                # Early exit: ≥2 complete lines of printable text
                                if buf.count("\n") >= _MIN_LINES and \
                                   any(c.isprintable() and not c.isspace() for c in buf):
                                    break
                            _time.sleep(0.1)
                        if buf.strip() and any(c.isprintable() and not c.isspace() for c in buf):
                            matched_baud = baud
                            output = buf[:200]
                            break
                except Exception:
                    continue

            stage.success = True
            stage.details = {
                "port": port, "matched_baud": matched_baud, "serial_output": output,
            }

            # Pattern match if expected is provided
            if expected:
                if not output:
                    stage.success = False
                    stage.error = f"No serial output received; expected pattern '{expected}'"
                    stage.details["expected"] = expected
                    stage.details["pattern_match"] = False
                else:
                    try:
                        if re.search(expected, output):
                            stage.details["pattern_match"] = True
                            stage.details["pattern"] = expected
                        else:
                            stage.success = False
                            stage.error = f"Serial output does not match expected pattern '{expected}'"
                            stage.details["pattern_match"] = False
                            stage.details["expected"] = expected
                            stage.details["actual"] = output[:200]
                    except re.error:
                        stage.details["pattern_error"] = f"Invalid regex: {expected}"

        except Exception as e:
            stage.success = True
            stage.details = {"note": f"Serial test skipped: {e}"}

        stage.elapsed_ms = (time.time() - t0) * 1000
        logger.info("S5 Test: %s", "baud=%d" % stage.details.get("matched_baud", 0) if stage.details.get("matched_baud") else "skipped")
        return stage

    def _default_chip(self) -> str:
        """Detect chip name from first available board config."""
        try:
            detector = self._detector
            for board in detector.list_available_boards(self._boards_dir):
                config = detector.resolve_board(board, boards_dir=self._boards_dir)
                if config and config.get("mcu", {}).get("chip"):
                    return config["mcu"]["chip"].lower()
        except Exception:
            pass
        return "atmega328p"


    # ===================================================================
    # Error handling
    # ===================================================================

    def _handle_build_error(self, build_result: Any, source_dir: str, board_id: str) -> None:
        """Record build error to experience ledger."""
        try:
            self._ledger.record_from_recovery(
                state="compile_fix",
                error_message=build_result.stderr[:200] if hasattr(build_result, "stderr") and build_result.stderr else "Build error",
                fix_applied="pending",
                source_file=source_dir,
                platform="arduino",
                board=board_id,
                tool="avr-gcc",
            )
        except Exception:
            pass
