"""Pipeline Runner — 5-Stage verification pipeline.

Stages: Detect (auto) → Review → Build → Flash → Test

Detect is automatic — always runs first to identify board/port.
State.json fingerprints drive incremental skip decisions.
"""

from __future__ import annotations

import datetime
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

from firmforge.core.experience_ledger import ExperienceLedger
from firmforge.core.board_detector import BoardDetector
from firmforge.core.source_reviewer import SourceReviewer, SourceReviewResult
from firmforge.core.confidence_scorer import ConfidenceScorer, ConfidenceReport
from firmforge.core.pipeline_state import PipelineState, compute_fingerprints
from firmforge.infrastructure import paths

logger = logging.getLogger(__name__)


def _salient_error(text: str, limit: int = 200) -> str:
    """从工具输出里挑一句「能看的」错误。

    不要直接切尾部：那把 traceback 从中间切断。实测 OpenOCD 失败时，
    stderr[-200:] 让终端显示成 `Error:  call last):` + 一堆 File "..."
    —— 判定没错，但人看不懂。优先取含 error/fail 的第一行，其次取最后一行非空。
    """
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    if not lines:
        return ""
    for ln in lines:
        low = ln.lower()
        if "error" in low or "fail" in low:
            return ln[:limit]
    return lines[-1][:limit]


def _artifact_info(path: str) -> dict[str, Any]:
    """产物的可核对信息：路径 + 时间 + 大小。

    跳过构建/烧录时必须打出来。只报一句 `[skipped]` 的话，「现在板上跑的
    是不是这份源码编的固件」只能自己去 dir 查 —— 而构建缓存在
    `cache/build/<板卡>/<项目>/` 下跨项目共享，查错目录的代价是烧错固件。
    文件不存在也照实报，不猜。
    """
    if not path:
        return {}
    p = Path(path)
    try:
        st = p.stat()
    except OSError:
        return {"firmware_path": path, "firmware_exists": False}
    return {
        "firmware_path": str(p),
        "firmware_exists": True,
        "firmware_mtime": datetime.datetime.fromtimestamp(
            st.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        "firmware_size": st.st_size,
    }


# S5 的六种结局。ff 只判断「有没有数据」和「调用方给的断言命中没有」，
# 不判断「这个输出是否说明功能实现了」——那是 Agent / 人的事。
VERDICT_VERIFIED = "verified"        # 调用方给了断言，且命中
VERDICT_MISMATCH = "mismatch"        # 调用方给了断言，但没命中（含 regex 非法）
VERDICT_COLLECTED = "collected"      # 采到数据，但没人给断言 —— 不算通过
VERDICT_EMPTY = "empty"              # 端口开着，一个字节都没回来
VERDICT_PORT_BUSY = "port_busy"      # 端口根本没打开 —— 前提缺失，固件没被检验
VERDICT_UNAVAILABLE = "unavailable"  # 没串口 / 没板卡配置 —— 这一步没执行
VERDICT_ERROR = "error"              # S5 自身异常


@dataclass
class VerifyDecision:
    """S5 判定的纯结果（不碰线程、不碰端口，便于测试）。"""

    success: bool
    verdict: str
    error: str = ""
    pattern_match: bool | None = None
    pattern_error: str = ""


def _decide_verify(sample_lines: list[str], expected: str,
                   port: str = "", baud: int = 0) -> VerifyDecision:
    """S5 判定。三条硬规则，全部机械可查：

    1. 一个字节都没收到 → 不通过（端口开着却没数据，本身就是问题）；
    2. 调用方给了断言且不命中 → 不通过（断言是调用方自己立的）；
    3. 采到数据但没给断言 → `collected`，**不是通过** —— 只报「我采到了」，
       不下「固件正常」的结论。

    断言的前提（调用方必须知道）：**只能断言周期性输出**（心跳 / 状态行）。
    端口是在烧录完成后才打开的，开跑前还会丢掉驱动缓冲里的残留字节，
    所以固件上电时打印一次的内容（版本横幅、初始化日志）**结构上采不到**。
    实测踩过：拿 `GC-H743 boot` 当断言，收到的其实是 `HEARTBEAT tick=1`，
    被判成 mismatch —— 看起来像固件不对，实际是断言选错了对象。
    """
    import re

    pattern_match: bool | None = None
    pattern_error = ""
    if expected:
        output = "\n".join(sample_lines)
        try:
            pattern_match = bool(re.search(expected, output))
        except re.error as exc:
            pattern_error = f"Invalid regex {expected!r}: {exc}"

    if pattern_error:
        return VerifyDecision(False, VERDICT_MISMATCH, pattern_error,
                              pattern_match, pattern_error)
    if not sample_lines:
        return VerifyDecision(
            False, VERDICT_EMPTY,
            f"串口 {port} 已打开（{baud} bps）但采样窗内没收到任何字节："
            "固件没在跑 / 波特率不符 / TX 未接到 RX / 固件只在启动时打印一次",
            pattern_match, pattern_error)
    if pattern_match is True:
        return VerifyDecision(True, VERDICT_VERIFIED, "", True, "")
    if pattern_match is False:
        return VerifyDecision(
            False, VERDICT_MISMATCH,
            f"输出未匹配 --expected {expected!r}；实际首行 {sample_lines[0][:100]!r}。"
            "断言只能针对周期性输出：端口在烧录完成后才打开，"
            "固件上电时打印一次的横幅/初始化日志采不到。",
            False, "")
    return VerifyDecision(True, VERDICT_COLLECTED, "", None, "")


@dataclass
class PipelineStage:
    """Result of a single pipeline stage."""
    stage: int
    name: str
    success: bool = False
    elapsed_ms: float = 0.0
    details: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    # 仅 S5 使用，取 verified / mismatch / collected / empty / unavailable。
    # success 是二态，表达不了「采到了数据但没人给断言」——那种情况既不是
    # 通过也不是失败，硬塞进任何一个都是在说假话。
    verdict: str = ""


@dataclass
class PipelineResult:
    """Aggregated pipeline execution result."""
    stages: list[PipelineStage] = field(default_factory=list)
    overall_success: bool = False
    board: str = ""
    #: 流水线**自身**的耗时（S1–S5），不含 S5 之后等面板的时间。
    total_elapsed_ms: float = 0.0
    #: S5 采完之后等面板关掉的时间。单独记：把它并进 total 会让一条真实
    #: 44 秒的流水线报成 444687 ms（2026-10-28 实测），那个数字随后会被
    #: 引用来做性能判断，而它衡量的是「人什么时候点 Stop」。
    panel_wait_ms: float = 0.0


class PipelineRunner:
    """Executes the 5-Stage verification pipeline.

    Usage:
        runner = PipelineRunner(boards_dir="./boards")
        result = runner.run_full(source_dir="boards/arduino_328p/apps/blink")
    """

    def __init__(
        self,
        boards_dir: str | Path | None = None,
        workspace: str | Path = ".",
        on_note: Callable[[str, str], None] | None = None,
    ) -> None:
        from firmforge.core.resources import boards_dir as _default_boards
        self._boards_dir = Path(boards_dir) if boards_dir else _default_boards()
        self._workspace = Path(workspace)
        # 阶段**内部**的进度行。`progress_callback` 只在阶段结束后触发，
        # 于是"cppcheck 要跑 100 秒"这件事在完成之前完全不可见 —— 对外表现
        # 就是卡死（2026-10-27 用户实测：静默 110 秒才轮到探针）。
        # core 只负责发出 `(阶段名, 一行人话)`，渲染归调用方，不在这里 print。
        self._on_note = on_note
        self._ledger = ExperienceLedger(paths.runtime_dir(workspace) / "ledger.jsonl")
        self._detector = BoardDetector(boards_dir=self._boards_dir)
        self._source_reviewer: SourceReviewer | None = None
        self._sr_chip: str | None = None  # chip of the cached source_reviewer
        self._sr_platform: str = ""       # board.yaml platform of the cached reviewer
        # 豁免表来源路径。同一进程里跑多个 app 时，各自的 .ff-review.yaml
        # 不同 —— 缓存键里不带它就会把上一个 app 的豁免套到下一个上。
        self._sr_allow_origin: str = ""
        self._confidence_scorer: ConfidenceScorer | None = None

    def _note(self, stage: str, message: str) -> None:
        """发一行阶段内进度。回调异常绝不打断流水线。"""
        if self._on_note is None:
            return
        try:
            self._on_note(stage, message)
        except Exception:                     # noqa: BLE001 — 打印失败不该坏事
            pass

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

    def build(self, source_dir: str, board_id: str | None = None,
              progress_callback: Callable[[str, bool, dict, str | None], None] | None = None,
              ) -> PipelineResult:
        """Run Detect + Review + Build only (no Flash/Test)."""
        return self.run_full(source_dir=source_dir, board_id=board_id,
                             stop_after="build",
                             progress_callback=progress_callback)

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
        """跑完整五阶段。

        ⚠ 名字有歧义：它跑的是**全流程**，不是只跑 S5。要只跑 S5（串口断言），
        用 ``run_full(only=("verify",))`` 或 CLI 的 ``ff verify``。
        2026-10-27 新增 ``ff verify`` 时才发现这个名字会误导：调用方以为
        「验证一下」= 只跑 S5，实际会连 cppcheck 一起跑 100 秒。
        """
        return self.run_full(source_dir=source_dir, board_id=board_id,
                             expected=expected)

    def run_full(
        self,
        source_dir: str | None = None,
        board_id: str | None = None,
        expected: str = "",
        stop_after: str = "",
        only: Sequence[str] = (),
        firmware: str = "",
        app_name: str = "",
        progress_callback: Callable[[str, bool, dict, str | None], None] | None = None,
        panel_open: str = "auto",
        panel_wait: float | None = None,
    ) -> PipelineResult:
        """Execute the 5-Stage Pipeline.

        Detect (auto) → Review → Build → Flash → Test

        Args:
            only: 只跑哪几个阶段（``"review"`` / ``"build"`` / ``"flash"`` /
                ``"verify"``）。空 = 全跑。S1 永远跑 —— 它只解析板卡配置，
                不是"执行动作"，少了它连走 SWD 还是 avrdude 都不知道。
            firmware: 只跑 flash 时直接指定 hex。空则按 state → 构建缓存解析。
            app_name: 只跑 flash 时用哪个应用名去构建缓存里找（`--app app`）。
        """
        want: set[str] = set(only) if only else {
            "review", "build", "flash", "verify"}
        if stop_after == "build":                 # 旧入口（ff build）的等价写法
            want = {"review", "build"}
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

        # 只有 Review/Build 需要源码目录。`ff flash` / `ff verify` 单独跑时
        # 没有 --app 也要能工作（否则"单独烧一份现成 hex"这条路直接被堵死）。
        if not source_dir and (want & {"review", "build"}):
            result.total_elapsed_ms = (time.time() - start) * 1000
            return result

        # -- Stage 2: Review (Code Review + Confidence Scoring) --
        if "review" in want:
            s2 = self._stage_review(board_id, source_dir or "",
                                    s1.details.get("config", {}))
            result.stages.append(s2)
            self._notify_progress(progress_callback, s2)
            if not s2.success:
                state.mark_failed("review", s2.error or "Review failed")
                state.save()
                result.total_elapsed_ms = (time.time() - start) * 1000
                return result

            state.mark_done("review")

        # Compute source fingerprint
        build_source = source_dir or ""
        fps = compute_fingerprints(
            board_id or "", detected_port, build_source, None,
        ) if build_source else {}

        # -- Stage 3: Build --
        if "build" in want:
            if state.should_skip_build(fps):
                fw_path = state.data.get("stages", {}).get("build", {}).get("hex", "")
                s3 = self._skipped_stage(3, "Build", "source unchanged, hex exists")
                s3.details.update(_artifact_info(fw_path))
                result.stages.append(s3)
                self._notify_progress(progress_callback, s3)
                if not fw_path:
                    s3.details["note"] = ("state 里没有记录上次的 hex 路径 —— "
                                          "无法确认复用的是什么（删 .ff-run 重跑）")
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
                fw_path = s3.details.get("firmware_path", "")
                state.mark_done("build", hex=fw_path)
                s3.details.update(_artifact_info(fw_path))
        else:
            # 不编译。**只有真要烧的时候才需要定位产物** —— `ff verify` 只连
            # 串口，不该因为「缓存里有两份 hex」就失败（第一次跑就撞上了）。
            fw_path = ""
            if "flash" in want:
                fw_path, fw_candidates, fw_why = self._resolve_firmware(
                    board_id or "", app_name or build_source, firmware, state)
                if not fw_path:
                    stage = PipelineStage(stage=4, name="Flash")
                    stage.success = False
                    stage.error = fw_why
                    stage.details = {"candidates": fw_candidates}
                    result.stages.append(stage)
                    self._notify_progress(progress_callback, stage)
                    result.total_elapsed_ms = (time.time() - start) * 1000
                    return result
                self._note("Flash", f"待烧产物：{fw_path}"
                                    + (f"（{fw_why}）" if fw_why else ""))

        if fps:
            fps = compute_fingerprints(
                board_id or "", detected_port, build_source, fw_path,
            )
        # 指纹必须在 S4/S5 的跳过判定**之后**才能落盘。
        # 以前在这里就 update_fingerprints(fps)，而 should_skip_flash/should_skip_test
        # 读的 stored 正是这个刚写入的 dict（同一对象）——自己跟自己比较恒为 True，
        # 于是只要历史上烧录成功过一次，之后源码/固件怎么改都不会再烧，板子上
        # 永远跑旧固件（S5 自然等不到新固件的输出）。

        if not (want & {"flash", "verify"}):
            if fps:
                state.update_fingerprints(fps)
            state.save()
            result.overall_success = all(s.success for s in result.stages)
            result.total_elapsed_ms = (time.time() - start) * 1000
            return result

        # -- Stage 4: Flash --
        # 只按指纹判定（board + source + hex + port）：源码或固件变了就必须重烧。
        # 不再附加 `or build_skipped` —— 那会让「源码没变但换了 COM 口」跳过烧录，
        # 新口上的板子留着旧固件。
        #
        # 给了断言（expected）时 **一律真烧**：state 里的 `flash=done` 只说明
        # *曾经*有某一轮把这份 hex 烧进去过，它无法证明 **此刻这块板上跑的就是
        # 这份固件**（换板、手动烧录、擦除、烧录中途失败都不会改 state）。
        # 跳过 S4 再跑 S5，得到的是一条误导链：「设备里是旧固件 → 串口 0 字节 →
        # 报波特率/TX 故障」。实测踩过一次（M-01 首轮，S4 显示 [skipped] 而
        # S5 空串口），代价是去查了硬件链路。
        flash_done_before = state.data.get("stages", {}).get("flash", {}).get("status") == "done"
        if "flash" not in want:
            # `ff verify` 单独跑：明确不烧，但要让人知道板上是什么
            flash_done_before = True
        elif not expected and flash_done_before and fps and state.should_skip_flash(fps):
            s4 = self._skipped_stage(4, "Flash", "fingerprints match")
            # 跳过烧录 = 板上跑的是**上次**烧进去的那份。必须说出来：
            # 否则「S3 换了新 hex、S4 显示 skipped」会被读成「新固件已生效」。
            s4.details["note"] = (f"未烧录，板上仍是上次烧的固件；"
                                  f"本次产物 {fw_path or '?'} 没有进芯片")
            result.stages.append(s4)
            self._notify_progress(progress_callback, s4)
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

        # Build stages summary for panel display (process + result)
        stages_summary_html, process_html = self._build_summary(result.stages)

        # -- Stage 5: Verify --
        # 有断言就必须验证（跳过等于没验证）；只有「没给断言 + 上次验证成功过」
        # 才允许走增量跳过。阶段名统一叫 Verify —— 以前跳过时叫 Test、真跑时
        # 叫 Verify，而 mcp_server 里按名字取 verdict/panel_url，跳过那次就取不到。
        s5: PipelineStage | None = None
        if "verify" not in want:
            pass
        elif not expected and flash_done_before and fps and state.should_skip_test(fps):
            s5 = self._skipped_stage(5, "Verify", "fingerprints match")
        else:
            s5 = self._stage_verify(board_id, expected, stages_summary=stages_summary_html, process_summary=process_html)
        if s5 is not None:
            result.stages.append(s5)
            self._notify_progress(progress_callback, s5)
            if s5.success:
                state.mark_done("test")
            else:
                # 没拿到证据就不能记成 done。should_skip_test 读的就是这个状态，
                # 记成 done 等于把「这次没验证成功」写进缓存：下一次调用直接跳过
                # S5、显示 [skipped]、overall_success=True —— 失败被粘成了通过。
                logger.info("S5 Verify: FAIL")
                verdict = getattr(s5, "verdict", "") or "error"
                state.mark_failed("test", s5.error or f"verify not passed ({verdict})")

        # 指纹在 S4/S5 的跳过判定全部结束之后才落盘（见上方注释）。
        if fps:
            state.update_fingerprints(fps)
        state.save()

        # 流水线的活到这一刻就干完了。后面等面板是**人的时间**，不是工具的时间，
        # 必须与总耗时分开记（否则一条 44 s 的流水线会报成 444687 ms）。
        work_ms = (time.time() - start) * 1000

        # Wait for collector thread to exit: Stop 按钮 / 关窗 / 超时
        # （`ff flash` / `ff review` 没有 S5，采集线程也不存在）
        if s5 is not None and hasattr(self, '_collector_alive') \
                and self._collector_alive.is_alive():
            # 面板地址必须打出来。ff 自己不负责开浏览器（全历史无 webbrowser/startfile），
            # 以前是 MCP 客户端拿 panel_url 去开窗；走 CLI 这条路时没人接手，
            # 如果不打印地址，S5 就等于没有面板。
            panel_url = s5.details.get("panel_url") or ""
            if panel_wait == 0:
                # 🔴 panel_wait=0 = 采样完立刻退出，HTTP 服务随进程一起消失。
                # 这时把地址打出来，人点开只会得到「连接被拒」——比不打更糟
                # （实测有人照着提示的地址去开，结论是「S5 面板不见了」）。
                # 地址仍留在 stage.details 里给 MCP / json 调用方：那边进程常驻，地址有效。
                logger.info(
                    "S5 面板未保留（panel_wait=0）：进程退出后地址即失效；"
                    "要实时看面板，用 --panel-wait 120（或去掉该参数常驻）")
            else:
                logger.info("S5 面板：%s", panel_url or "(未启动)")
            self._maybe_open_panel(panel_url, panel_open, panel_wait)
            if panel_wait == 0:
                logger.info("S5 不等面板（panel_wait=0），采样完即结束")
            elif panel_wait:
                logger.info("S5 panel live — 点 Stop / 关窗结束，或 %.0fs 后自动结束", panel_wait)
            else:
                logger.info("S5 panel live — 点 Stop 或关窗结束（无限等）")
            try:
                self._collector_alive.join(timeout=panel_wait)
            except KeyboardInterrupt:
                pass

            # panel_wait 有限（0 或 N 秒）意味着「命令就在此刻结束」：采集线程
            # 若还活着必须显式叫停并等它关闭串口。它是 daemon 线程，不写 stop
            # 文件就会一直持有 COM 口，于是下一次 flash 打不开端口——表现为
            # 1 秒内走完所有波特率、bytes_written=0 的「假失败」。
            if panel_wait is not None and self._collector_alive.is_alive():
                stop_path = getattr(self, "_collector_stop_path", "")
                if stop_path:
                    try:
                        with open(stop_path, "w", encoding="utf-8") as f:
                            f.write("stop\n")
                    except OSError as e:
                        logger.warning("S5 无法写入 stop 文件 %s: %s", stop_path, e)
                # join() 返回 None（不是 bool），必须用 is_alive() 判定，
                # 否则 `if not join(...)` 恒为真 —— 每次都会报「5s 内未退出」，
                # 把唯一的端口占用告警变成人人忽略的噪声。
                self._collector_alive.join(timeout=5.0)
                if self._collector_alive.is_alive():
                    logger.warning("S5 采集线程 5s 内未退出，COM 口可能仍被占用")
                elif stop_path:
                    # 线程已退出：立刻清掉停止文件。留着它等于给下一次运行埋雷
                    # ——任何没做清理的入口（面板、手工 monitor）进来第一轮就被赶走。
                    try:
                        os.remove(stop_path)
                    except OSError:
                        pass

        result.overall_success = all(s.success for s in result.stages)
        result.total_elapsed_ms = work_ms
        result.panel_wait_ms = max(0.0, (time.time() - start) * 1000 - work_ms)
        return result

    @staticmethod
    def _maybe_open_panel(url: str, mode: str, wait: float | None) -> None:
        """把面板地址送到人眼前——只在"确实有人在看"的场景开窗。

        分工：ff 负责提供地址（永远打印），**用什么容器呈现归调用方**。
        auto 的判据全是现成事实，不猜：
          - stdout 是 tty？否则说明被 IDE / 脚本接管
          - CI / SSH 环境变量存在？否则说明可能是无 GUI 的远端
        开窗失败只记 debug，绝不因为浏览器起不来而判失败。
        """
        if not url or wait == 0:
            return
        mode = (mode or "auto").strip().lower()
        if mode == "none":
            return
        if mode == "auto":
            import os
            import sys
            if not sys.stdout.isatty():
                return
            if os.environ.get("CI") or os.environ.get("SSH_CONNECTION"):
                return
        try:
            import webbrowser
            webbrowser.open(url)
            logger.info("S5 面板已打开：%s", url)
        except Exception as e:  # 无 GUI / 无浏览器：不影响流程
            logger.debug("open panel failed: %s", e)

    @staticmethod
    def _build_summary(stages) -> tuple[str, str]:
        """Build panel top-bar summaries from stage results.

        Returns (stages_html, process_html):
          stages:  icons per stage — ✅绿 ⚠️黄 ❌红 🔄蓝 + elapsed ms
          process: S2:(cppcheck:err/warn,register) S3:build×n S4:flash@baud
        """
        process_parts = []
        result_icons = []
        for _s in stages:
            if _s.success:
                # Process details
                if _s.stage == 2:
                    cpp = len(_s.details.get("cppcheck") or [])
                    cpp_err = sum(1 for w in (_s.details.get("cppcheck") or []) if w.get("severity") == "error")
                    cpp_warn = cpp - cpp_err
                    reg = len(_s.details.get("warnings") or [])
                    _items = []
                    if cpp_err: _items.append(f"cppcheck:err={cpp_err}")
                    if cpp_warn: _items.append(f"cppcheck:warn={cpp_warn}")
                    if reg: _items.append(f"register={reg}")
                    if _items:
                        process_parts.append(f'S2:({",".join(_items)})')
                elif _s.stage == 3:
                    process_parts.append(f'S3:build&times;{_s.details.get("compile_rounds",1)}')
                elif _s.stage == 4:
                    baud = _s.details.get("baud", 115200)
                    process_parts.append(f'S4:flash@{baud}(retry={_s.details.get("baud_retries",0)})')

                # Result icon with color: ✅绿 ⚠️黄 ❌红 🔄蓝
                if _s.stage == 2:
                    cpp_all = _s.details.get("cppcheck") or []
                    cpp_err = sum(1 for w in cpp_all if w.get("severity") == "error")
                    if cpp_err:
                        _icon = "&#10060;"; _color = "#ef4444"  # ❌ error = red
                    elif cpp_all:
                        _icon = "&#9888;"; _color = "#eab308"   # ⚠ cppcheck = yellow
                    elif _s.details.get("warnings"):
                        _icon = "&#9888;"; _color = "#eab308"   # ⚠ register = yellow
                    else:
                        _icon = "&#9989;"; _color = "#4ade80"   # ✅ clean = green
                elif _s.stage == 3 and _s.details.get("compile_rounds", 1) > 1:
                    _icon = "&#128260;"; _color = "#22d3ee"     # 🔄 retry = blue
                elif _s.stage == 4 and _s.details.get("baud_retries", 0) > 0:
                    _icon = "&#128260;"; _color = "#22d3ee"     # 🔄 retry = blue
                else:
                    _icon = "&#9989;"; _color = "#4ade80"       # ✅ pass = green
                result_icons.append(f'<span style="color:{_color}">{_icon}</span><span style="color:var(--dim)">S{_s.stage}:{int(_s.elapsed_ms)}ms</span>')
            else:
                result_icons.append(f'<span style="color:#ef4444">&#10060;</span><span style="color:var(--dim)">S{_s.stage}:FAIL</span>')
        return ("  ".join(result_icons), "  ".join(process_parts) if process_parts else "")

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
        """Write serial_live.html static snapshot after ff_run."""
        if not source_dir:
            return
        output = s5.details.get("serial_output", "") if s5.details else ""
        baud = s5.details.get("matched_baud", 0) if s5.details else 0
        port = s5.details.get("port", "?") if s5.details else "?"
        html_path = paths.runtime_dir(self._workspace) / "serial_live.html"
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
  <span>{source_dir or "ff_run"}</span>
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

        # board_id 已由 resolve_board() 注入（唯一注入点），此处不再重复。
        stage.success = True
        stage.details = {"board_id": board_id, "config": config}
        stage.elapsed_ms = (time.time() - t0) * 1000
        logger.debug("S1 Detect: %s", board_id)
        return stage

    # ===================================================================
    # Stage 2: Review
    # ===================================================================

    def _stage_review(self, board_id: str | None, source_dir: str,
                      board_config: dict) -> PipelineStage:
        stage = PipelineStage(stage=2, name="Review")
        t0 = time.time()

        # Phase 1: Cppcheck static analysis (logic bugs, uninit vars, etc.)
        #
        # 纪律（2026-10-27 修）：**工具说了什么就往上带什么**。此前的写法只留
        # 两个聚合数字（`len(warnings)` / `errors`），于是
        #   ① 解析层把 Windows 路径的盘符冒号切错 → severity 变成行号字符串
        #      → error 恒为 0 → 闸门静默失效，日志却报 "0 errors"；
        #   ② 就算计数对，没有文件名行号，读日志的人也无从下手。
        # 现在：明细（file:line: id message）+ 原始输出 + 分桶计数 + 降级说明
        # 全部进 details，日志按 error 打点，不靠一个数字让人猜。
        cp = self._run_cppcheck(board_id, source_dir, board_config)
        cppcheck_errors = len(cp.blocking)

        # Phase 2: Register review (hallucinated register detection)
        self._note("Review", "寄存器审查：对照知识库解析外设/寄存器/位域引用…")
        c_result = self._review_check(board_id, source_dir, board_config)
        review_ok = not c_result or c_result.passed
        if c_result:
            judged = max(0, c_result.registers_checked - c_result.kb_gaps)
            self._note("Review",
                       f"寄存器审查 {c_result.registers_resolved}/{judged}"
                       f" · 字段 {c_result.fields_resolved}/{c_result.fields_checked}"
                       + (f" · 知识库缺口 {c_result.kb_gaps}（不判定）"
                          if c_result.kb_gaps else "")
                       + (f" · 已豁免 {len(c_result.allowed)}"
                          if c_result.allowed else "")
                       + f" → {'PASS' if review_ok else 'FAIL'}")

        # Phase 3: Confidence Scoring
        conf_result = self._confidence_check(board_id, source_dir, c_result, board_config)
        conf_ok = not (conf_result and conf_result.needs_review)
        if conf_result:
            cats = " · ".join(
                f"{k} {v.score:.0f}%" for k, v in conf_result.category_scores.items()
                if v.checked)
            self._note("Review", f"Confidence {conf_result.overall_score:.0f}%"
                                 + (f"（{cats}）" if cats else ""))

        sub_stages = [
            {"name": "cppcheck", "success": cp.ok and cppcheck_errors == 0,
             "issues": len(cp.issues), "errors": cppcheck_errors,
             "vendor_errors": len(cp.vendor_errors),
             "status": cp.status, "cached": cp.cached},
            {"name": "review", "success": review_ok,
             "violations": len(c_result.violations) if c_result else 0,
             "registers": [v.register for v in c_result.violations[:10]] if c_result else [],
             # 「知识库缺口」与「幻觉」分开计：前者是工具的收录不全，后者才是
             # 源码写错。混成一个数字，用户没法判断该改代码还是该补库。
             "kb_gaps": c_result.kb_gaps if c_result else 0,
             "allowed": len(c_result.allowed) if c_result else 0,
             "cross_checked": c_result.cross_checked if c_result else False},
            {"name": "confidence", "success": conf_ok,
             "score": conf_result.overall_score if conf_result else 100,
             "review_items": len(conf_result.review_items) if conf_result else 0,
             # 分项 —— 一个数字说不清"哪一块低"，分项能。
             "categories": ({k: {"checked": v.checked, "resolved": v.resolved,
                                 "score": round(v.score, 1)}
                             for k, v in conf_result.category_scores.items()}
                            if conf_result else {}),
             "explanation": conf_result.explanation if conf_result else ""},
        ]

        # Build review details — 三类明细全部保留，供人读也供 Agent 读
        details: dict[str, Any] = {
            "sub_stages": sub_stages,
            "cppcheck": [i.as_dict() for i in cp.issues],
            "cppcheck_meta": [i.as_dict() for i in cp.meta],
            "cppcheck_unparsed": list(cp.unparsed),
            "cppcheck_buckets": [{"id": k, "count": v} for k, v in cp.buckets()],
            "cppcheck_status": cp.status,
            "cppcheck_notes": list(cp.notes),
            "cppcheck_command": list(cp.command),
            "cppcheck_raw": cp.raw,
            "cppcheck_elapsed_ms": round(cp.elapsed_ms, 1),
        }
        if c_result:
            details["warnings"] = [
                {"file": v.file, "register": v.register, "field": v.field,
                 "line": v.line, "severity": v.severity,
                 "text": v.line_text.strip()[:80],
                 "reason": v.reason, "suggestion": v.suggestion,
                 # 三态：error=阻断 / warning=线索 / kb-gap=工具缺口 /
                 # allowed=项目已声明豁免。Agent 据此决定该改哪一边。
                 "status": ("allowed" if v.allowed_reason
                            else "kb-gap" if v.kb_gap else v.severity),
                 "evidence": v.evidence,
                 "allowed_reason": v.allowed_reason}
                for v in (c_result.violations + c_result.warnings
                          + c_result.allowed)[:20]
            ]
            details["review_counts"] = {
                "registers_checked": c_result.registers_checked,
                "registers_resolved": c_result.registers_resolved,
                "fields_checked": c_result.fields_checked,
                "fields_resolved": c_result.fields_resolved,
                "kb_gaps": c_result.kb_gaps,
                "allowed": len(c_result.allowed),
                "cross_checked": c_result.cross_checked,
            }
        if conf_result:
            details["confidence"] = {
                "score": round(conf_result.overall_score, 1),
                "explanation": conf_result.explanation,
                "checks": len(conf_result.checks),
                "categories": {k: {"checked": v.checked,
                                    "resolved": v.resolved,
                                    "score": round(v.score, 1),
                                    "note": v.note}
                                for k, v in conf_result.category_scores.items()},
                "review_items": [
                    {"category": c.category, "identifier": c.identifier,
                     "score": round(c.score, 1), "note": c.note}
                    for c in conf_result.review_items[:20]
                ],
            }

        # -- 日志：先打"分析有没有跑成"，再打每一条 error 的落点 ----------
        if not cp.ok:
            # 没跑成 ≠ 没问题。旧写法这时会安静地报 0 errors。
            logger.warning("S2 Review: 静态分析未完成 —— %s", cp.summary_line())
        else:
            logger.debug("S2 Review: cppcheck %s（%s）",
                        cp.summary_line(),
                        ", ".join(f"{k}×{v}" for k, v in cp.buckets()[:6]) or "无诊断")
            if cp.cached:
                logger.debug("S2 Review: cppcheck 结果来自内容哈希缓存")
        for issue in cp.blocking[:20]:
            logger.warning("  [cppcheck error] %s  %s: %s",
                           issue.where(), issue.id, issue.message)
        if len(cp.blocking) > 20:
            logger.warning("  … 另有 %d 条 error 未逐条打印（--json 可看全量）",
                           len(cp.blocking) - 20)
        # 厂家库里的 error 照实打出来，但不计入阻断（CMSIS/HAL 是官方代码，
        # 它过不过 cppcheck 与用户固件对不对无关）。不打印等于藏起来。
        for issue in cp.vendor_errors[:10]:
            logger.info("  [vendor error] %s  %s: %s",
                        issue.where(), issue.id, issue.message)
        if len(cp.vendor_errors) > 10:
            logger.info("  … 厂家库另有 %d 条 error（不阻断）",
                        len(cp.vendor_errors) - 10)
        for note in cp.notes:
            logger.warning("S2 Review: %s", note)

        if not review_ok:
            # 文件名 + 行号 + 寄存器名，一个都不能少：只给计数等于让读日志的
            # 人自己写脚本复现（本来就发生过）。
            gap_note = (f"，另有 {c_result.kb_gaps} 条属知识库缺口"
                        if c_result and c_result.kb_gaps else "")
            logger.warning("Code Review: FAIL —— %d 处引用校验未通过（不阻断）%s",
                           len(c_result.violations), gap_note)
            for v in c_result.violations[:20]:
                where = f"{v.file}:{v.line}" if v.file else f"line {v.line}"
                logger.warning("  [review] %s  %s  %s", where,
                               f"{v.register}.{v.field}" if v.field else v.register,
                               v.reason + (f"（{v.evidence}）" if v.evidence else ""))
            if len(c_result.violations) > 20:
                logger.warning("  … 另有 %d 条未逐条打印（--json 可看全量）",
                               len(c_result.violations) - 20)

        # 知识库缺口单独一段：它不是源码错误，混在 FAIL 明细里会被当成待修 bug
        if c_result and c_result.kb_gaps:
            logger.info("Code Review: %d 条知识库缺口（芯片上有、库未收录）—— "
                        "这些不计入失败，源码无需改动", c_result.kb_gaps)
            for v in [x for x in c_result.warnings if x.kb_gap][:10]:
                logger.info("  [kb-gap] %s:%s  %s  %s", v.file, v.line,
                            v.register, v.evidence)

        # 已声明豁免的条目照原样列出，标注理由 —— 豁免不等于看不见
        if c_result:
            for v in c_result.allowed[:10]:
                logger.info("  [allowed] %s:%s  %s —— 项目已声明豁免：%s",
                            v.file, v.line, v.register, v.allowed_reason)

        if conf_result and conf_result.explanation:
            logger.warning("Confidence %.0f%% —— %s",
                           conf_result.overall_score, conf_result.explanation)
        for key, cat in (conf_result.category_scores.items() if conf_result else []):
            if cat.checked:
                logger.debug("  [confidence] %s", cat)
        for item in (conf_result.review_items[:10] if conf_result else []):
            logger.warning("  [confidence] %s %s = %.0f%%  %s",
                           item.category, item.identifier, item.score, item.note)

        if cppcheck_errors:
            stage.success = False
            stage.error = (
                f"Cppcheck: {cppcheck_errors} 处 error —— "
                + "; ".join(f"{i.where()} {i.id}" for i in cp.blocking[:5])
                + (" …" if len(cp.blocking) > 5 else ""))
            stage.details = details
            stage.elapsed_ms = (time.time() - t0) * 1000
            logger.warning("S2 Review: BLOCKED (%d cppcheck errors)", cppcheck_errors)
            return stage

        stage.success = True     # S2 is non-blocking for warnings/style only
        stage.details = details

        stage.elapsed_ms = (time.time() - t0) * 1000
        logger.debug("S2 Review: PASS (cppcheck=%d, register=%d)",
                     len(cp.issues),
                     len(c_result.violations) if c_result else 0)
        return stage

    # ------------------------------------------------------------------
    # S2 Phase 1：cppcheck
    # ------------------------------------------------------------------

    def _run_cppcheck(self, board_id: str | None, source_dir: str | None,
                      board_config: dict):
        """跑 cppcheck，并用**编译用的同一份** include / 宏 / 内建宏喂它。

        拿不到构建上下文不等于不跑 —— 但要把"结果带水分"这件事写进 notes。
        返回 `CppcheckReport`；任何异常都落成一个 `ok=False` 的报告，
        绝不是一个空列表（空列表的含义是"干净"，两者不能混）。
        """
        from firmforge.providers.arduino.cppcheck import CppcheckReport, run_cppcheck

        if not source_dir:
            return CppcheckReport(ok=False, status="skipped",
                                  skip_reason="没有源码目录")

        include_dirs: list[str] = []
        defines: list[str] = []
        force_includes: list[str] = []
        vendor_roots: list[str] = []
        context_problems: list[str] = []
        try:
            from firmforge.providers import get_build_provider
            cfg = board_config or {}
            builder = get_build_provider(cfg.get("platform", "arduino"), cfg)
            getter = getattr(builder, "cppcheck_context", None)
            if getter is None:
                context_problems.append(
                    f"{type(builder).__name__} 未提供 cppcheck_context()")
            else:
                ctx = getter()
                include_dirs = list(getattr(ctx, "include_dirs", []))
                defines = list(getattr(ctx, "defines", []))
                force_includes = list(getattr(ctx, "force_includes", []))
                vendor_roots = list(getattr(ctx, "vendor_roots", []))
                context_problems = list(getattr(ctx, "problems", []))
        except Exception as exc:                     # 提供者缺失/构造失败
            context_problems.append(f"取构建上下文失败：{type(exc).__name__}: {exc}")

        tu = self._count_translation_units(source_dir)
        # 这条是「卡死」感受的分界线：它必须在 cppcheck **启动之前**出现。
        # 冷跑时 cppcheck 要 100 秒左右（CMSIS/HAL 头巨量展开），期间进程
        # 一声不吭，从外面完全看不出是在干活还是挂了。
        jobs, bdir = self._cppcheck_speed(source_dir)
        self._note("Review", f"cppcheck 启动（{tu} 个翻译单元，"
                             f"{len(include_dirs)} 个 include 目录，"
                             f"-j {jobs}，增量目录 {'有' if bdir else '无'}）")
        t_cpp = time.time()
        try:
            report = run_cppcheck(source_dir, include_dirs=include_dirs,
                                  defines=defines,
                                  force_includes=force_includes,
                                  vendor_roots=vendor_roots,
                                  jobs=jobs, build_dir=bdir)
        except Exception as exc:
            return CppcheckReport(ok=False, status="crashed",
                                  skip_reason=f"{type(exc).__name__}: {exc}")
        spent = time.time() - t_cpp
        if report.cached:
            self._note("Review",
                       f"cppcheck 命中缓存（{spent * 1000:.0f} ms，源码与 include 头"
                       f"逐字节未变）：{len(report.issues)} 条诊断 / "
                       f"error {len(report.blocking)}")
        else:
            self._note("Review",
                       f"cppcheck 完成 {spent:.1f}s："
                       f"error {len(report.blocking)} / warning {len(report.warnings)}"
                       + (f" / 厂家库 error {len(report.vendor_errors)}（不阻断）"
                          if report.vendor_errors else "")
                       + ("" if report.ok else f"（未跑成：{report.status}）"))
        for problem in context_problems:
            report.notes.append(f"构建上下文不完整：{problem}")
        return report

    @staticmethod
    def _cppcheck_speed(source_dir: str) -> tuple[int, str]:
        """cppcheck 的并行度与增量目录。

        实测（8 个 TU，STM32H743 + CMSIS/HAL，2026-10-27）：

            整目录单进程                121.7 s
            -j 8                         72.2 s
            -j 8 + build-dir（首次）     65.4 s
            -j 8 + build-dir（未改）     12.3 s
            -j 8 + build-dir（改 1 文件）10.9 s

        进程级内容哈希缓存（`_cache_key`）只在「一个字节都没变」时命中，
        改一行就全废；`--cppcheck-build-dir` 是按翻译单元复用的，两者互补。
        并行度上限取 8：cppcheck 每个进程都要把 CMSIS 头展开一遍，核数再多
        只是把内存吃满，实测 8 已经到底。
        """
        jobs = max(1, min(8, os.cpu_count() or 4))
        bdir = ""
        if source_dir:
            try:
                import hashlib
                tag = hashlib.sha256(
                    str(Path(source_dir).resolve()).encode("utf-8")).hexdigest()[:12]
                bdir = str(paths.cache_dir() / "cppcheck" / "build" / tag)
            except Exception:                     # noqa: BLE001 — 加速失败不能坏事
                bdir = ""
        return jobs, bdir

    @staticmethod
    def _count_translation_units(source_dir: str) -> int:
        """数 `.c/.cpp/.ino` 数量。只用于进度提示，数错了不影响任何判定。"""
        try:
            root = Path(source_dir)
            return sum(1 for ext in ("*.c", "*.cpp", "*.ino")
                       for f in root.rglob(ext) if f.is_file())
        except OSError:
            return 0


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

    def _resolve_board_config(self, board_id: str | None) -> dict[str, Any] | None:
        """board_id → board.yaml 定义（含注入的 board_id）。解析失败返回 None。"""
        if not board_id:
            return None
        try:
            return self._detector.resolve_board(board_id, boards_dir=self._boards_dir)
        except Exception:
            return None

    def _resolve_chip(self, board_id: str | None) -> str:
        """Resolve chip name from board_id -> board.json -> mcu.chip."""
        config = self._resolve_board_config(board_id)
        if config and config.get("mcu", {}).get("chip"):
            return config["mcu"]["chip"].lower()
        return self._default_chip()

    def _get_source_reviewer(self, board_id: str | None = None,
                              source_dir: str | None = None) -> SourceReviewer:
        from firmforge.core.review_allowlist import ReviewAllowlist, summarize
        from firmforge.knowledge.device_truth import DeviceTruth

        config = self._resolve_board_config(board_id)
        chip = ((config or {}).get("mcu", {}).get("chip") or "").lower() \
            or self._default_chip()
        # 缓存键含平台：同一芯片在不同板卡上可能走不同寄存器库（不可能，
        # 但 `hal`/`arduino` 范式并存时平台路由不同，键里带上更安全）。
        platform = (config or {}).get("platform", "")
        allowlist = ReviewAllowlist.load(source_dir) if source_dir \
            else ReviewAllowlist()
        if self._sr_chip != chip or self._sr_platform != platform \
                or self._sr_allow_origin != allowlist.origin \
                or self._source_reviewer is None:
            self._load_knowledge_base(chip, config)
            self._source_reviewer = SourceReviewer(
                self._knowledge_base,
                # 器件头是「未收录 vs 幻觉」的第二判据。没有它时审查只能报
                # warning —— 不知道就说不知道，不能把库的缺口当源码的错。
                device_truth=DeviceTruth.load(chip),
                allowlist=allowlist,
            )
            self._sr_chip = chip
            self._sr_platform = platform
            self._sr_allow_origin = allowlist.origin
            truth = self._source_reviewer.device_truth
            logger.debug("SourceReviewer init for chip=%s platform=%s 器件头=%s",
                        chip, platform or "?",
                        "有" if truth is not None and truth.available else "无")
            summary = summarize(allowlist)
            if summary:
                logger.info("%s", summary)
            for problem in allowlist.problems:
                logger.warning("审查豁免表：%s", problem)
        return self._source_reviewer

    def _load_knowledge_base(self, chip: str,
                             board_config: dict[str, Any] | None = None) -> None:
        """Load KnowledgeBase for the given chip, caching on self._knowledge_base.

        ``board_config`` 给了就按板卡路由平台（``board.yaml: platform`` →
        寄存器库目录名，见 ``knowledge.platforms``）；没给则退回 AVR ——
        历史默认，别再往这里加新平台分支，平台名不该在核心层出现。
        """
        platform = (board_config or {}).get("platform", "")
        from firmforge.knowledge.platforms import device_series
        series = device_series(board_config, chip)
        if getattr(self, "_knowledge_base_chip", None) != chip \
                or getattr(self, "_knowledge_base_platform", None) != platform \
                or getattr(self, "_knowledge_base_series", None) != series \
                or not hasattr(self, "_knowledge_base"):
            from firmforge.knowledge.knowledge_base import KnowledgeBase
            from firmforge.knowledge.platforms import library_platform
            self._knowledge_base = KnowledgeBase()
            library = library_platform(board_config)
            if not self._knowledge_base.load_reference(library, chip=chip,
                                                       series=series):
                logger.warning("KnowledgeBase empty for %s/%s/%s — S2 register "
                               "review will not resolve anything",
                               library, series or "-", chip)
            self._knowledge_base_chip = chip
            self._knowledge_base_platform = platform
            self._knowledge_base_series = series

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
            validator = self._get_source_reviewer(board_id, source_dir)
            if not source_path.is_dir():
                return None
            # Aggregate results across all source files
            aggregated = SourceReviewResult()
            for f in sorted(source_path.rglob("*")):
                if f.suffix in (".c", ".cpp", ".h", ".ino") and f.is_file():
                    result = validator.validate_file(str(f))
                    aggregated.violations.extend(result.violations)
                    aggregated.warnings.extend(result.warnings)
                    aggregated.allowed.extend(result.allowed)
                    aggregated.kb_gaps += result.kb_gaps
                    aggregated.registers_allowed += result.registers_allowed
                    aggregated.cross_checked = result.cross_checked
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
                self._load_knowledge_base(chip, self._resolve_board_config(board_id))
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
            # board_id 已由 resolve_board() 注入；此处只需补 knowledge_base
            # 引脚查询用的别名键（`board_alias_<alias>`）。board_id 的赋值
            # 保留为幂等防御，兼容直接传入裸 config 的调用方（如测试）。
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

    def _resolve_firmware(self, board_id: str, app_hint: str,
                          explicit: str, state: "PipelineState",
                          ) -> tuple[str, list[dict[str, Any]], str]:
        """定位「要烧哪一份固件」。返回 ``(路径, 候选列表, 说明)``。

        顺序：显式指定 → state 记录 → 构建缓存里**唯一**那一份。

        构建缓存下有多份时**报错并列候选，绝不挑「最新」**。2026-10-27 的
        事故正是「取最新」：`ff inspect` 拿 hello_blink 的 ELF 去解析 app 的
        PC，输出了一条 `main.c:555` —— 看起来完全合理，比直接报错危险得多。
        烧录比解析更狠：猜错就是把别人的固件烧进板子。
        """
        if explicit:
            p = Path(explicit)
            if p.is_file():
                return str(p), [], "显式指定 --firmware"
            return "", [], f"指定的固件不存在：{explicit}"

        cache = paths.build_cache_dir() / (board_id or "unknown")
        found = sorted(cache.glob("*/firmware.hex")) if cache.is_dir() else []

        def _candidates() -> list[dict[str, Any]]:
            out = []
            for f in found:
                try:
                    st = f.stat()
                except OSError:
                    continue
                out.append({
                    "app": f.parent.name,
                    "path": str(f),
                    "size": st.st_size,
                    "mtime": time.strftime("%Y-%m-%d %H:%M:%S",
                                           time.localtime(st.st_mtime)),
                })
            return out

        # `--app` 在 state 之前：用户点名要某个应用，就不该被上一次构建
        # 留下的记录覆盖。顺序反了的话 `ff flash X --app other` 会安静地
        # 烧上一份（state 里那份）—— 与 `ff inspect` 那次「取最新 ELF」
        # 是同一类错误：给出的答案看起来完全合理。
        if app_hint:
            one = cache / Path(app_hint).name / "firmware.hex"
            if one.is_file():
                return str(one), [], "构建缓存（按 --app 定位）"
            names = "、".join(c["app"] for c in _candidates()) or "（空）"
            return "", _candidates(), (
                f"--app {Path(app_hint).name} 在构建缓存里没有产物（{cache}）。"
                f"现有：{names}。先跑 ff build --app {app_hint}，"
                f"或用 --firmware <路径> 指定")

        recorded = (state.data.get("stages", {}).get("build", {}) or {}).get("hex", "")
        if recorded and Path(recorded).is_file():
            return recorded, [], "state 记录的上次构建产物"

        if len(found) == 1:
            return str(found[0]), [], "构建缓存（仅此一份）"
        if not found:
            return "", [], (f"找不到可烧的固件：{cache} 下没有 firmware.hex。"
                            f"先跑 ff build，或用 --firmware <path> 指定")

        cands = _candidates()
        names = "、".join(c["app"] for c in cands)
        return "", cands, (f"构建缓存里有 {len(cands)} 份 firmware.hex，无法判断要烧哪一份"
                           f"（{names}）。用 --app <应用名> 或 --firmware <路径> 指定")

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
            # Artifacts go to B 区 `cache/build/<board>/<app>/`, never into the
            # A 区 source tree (标准 §5 R2：派生物不得物理位于承诺级目录).
            app_name = Path(source_dir).name
            output_dir = str(paths.build_cache_dir()
                             / (board_id or "unknown") / app_name)
            self._note("Build", f"编译启动：{app_name} → {output_dir}")
            t_build = time.time()
            build_result = builder.build(source_dir, output_dir=output_dir)
            if build_result.success:
                self._note("Build", f"编译完成 {time.time() - t_build:.1f}s"
                                    f"（{build_result.firmware_path or '无产物路径'}）")
            else:
                self._note("Build", f"编译失败 {time.time() - t_build:.1f}s"
                                    f"（{len(build_result.errors)} 条 error）")

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
        logger.debug("S3 Build: %s", "PASS" if stage.success else "FAIL")
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
            # avrdude 路线必须有串口 —— 这条前提检查原先只在 CLI 的
            # `cmd_flash` 里有，改走流水线后要搬过来，否则「没插板子」
            # 会一路传到 avrdude 的报错文本，变成一条看不懂的失败。
            # SWD 路线不适用：探针走 USB HID，本来就没有串口。
            if config.get("platform", "arduino") == "arduino" \
                    and not flasher.detect_port():
                stage.success = False
                stage.error = ("No COM port detected —— arduino 走 avrdude，"
                               "必须有串口。检查数据线与 CH340 驱动后重试")
                stage.elapsed_ms = (time.time() - t0) * 1000
                return stage
            size = Path(firmware_path).stat().st_size
            self._note("Flash", f"烧录启动（{Path(firmware_path).name}，{size} B，"
                                f"{config.get('flash', {}).get('transport', 'swd') if isinstance(config.get('flash'), dict) else 'swd'}）")
            flash_result = flasher.flash(firmware_path)

            stage.success = flash_result.success
            stage.details = {
                "bytes_written": flash_result.bytes_written if hasattr(flash_result, "bytes_written") else 0,
                "elapsed_flash_ms": flash_result.elapsed_ms if hasattr(flash_result, "elapsed_ms") else 0,
                "baud_retries": getattr(flash_result, "baud_retries", 0),
            }
            if not flash_result.success:
                stage.error = _salient_error(getattr(flash_result, "stderr", "")) or "Flash failed"

        except ImportError as e:
            stage.success = False
            stage.error = f"FlashProvider not available: {e}"
        except Exception as e:                     # noqa: BLE001
            # 可预期的烧录失败（工具链缺件、探针没插、校验不过）必须落成
            # 一行 stage.error，不能把 traceback 抛给调用方 —— `ff flash`
            # 以前在 CLI 里专门 catch 过 ProviderError，改走流水线后这条
            # 保护要跟着搬过来，否则「探针没插」会变成一屏栈。
            from firmforge.providers.base import ProviderError
            if not isinstance(e, ProviderError):
                raise
            stage.success = False
            stage.error = str(e)

        stage.elapsed_ms = (time.time() - t0) * 1000
        logger.debug("S4 Flash: %s", "PASS" if stage.success else "FAIL")
        return stage

    # ===================================================================
    # Stage 5: Test
    # ===================================================================

    def _stage_verify(self, board_id: str | None, expected: str = "",
                       stages_summary: str = "", process_summary: str = "") -> PipelineStage:
        """S5 Verify — start collector thread, get 3 sample lines, return.

        Thread-based (no subprocess). Collector runs in daemon thread.
        Agent gets sample_lines. User opens panel for live view.
        """
        stage = PipelineStage(stage=5, name="Verify")
        t0 = time.time()

        try:
            import threading
            import json
            from pathlib import Path
            # 工作区 = 本次调用的 workspace —— state.json 本来就在它下面。
            # 以前这里是 `Path(__file__)` 上溯三级，那是**工具自己的安装目录**，
            # 于是面板文件写进源码树/site-packages，而状态写进真工作区：同一个
            # 会话被劈成两半，且 serial_config.json 变成全局一份，任何一个
            # 工作区的面板操作都会改掉所有工作区的验证串口参数（实测踩过一次）。
            root = Path(self._workspace)

            from firmforge.providers import get_flash_provider
            detector = self._detector
            config = detector.resolve_board(board_id or "", boards_dir=self._boards_dir)
            if not config:
                stage.success = True
                stage.verdict = "unavailable"
                stage.details = {"note": "No board config", "skipped": True}
                stage.elapsed_ms = (time.time() - t0) * 1000
                return stage

            flasher = get_flash_provider(config.get("platform", "arduino"), config)
            port = flasher.detect_port()
            if not port:
                # 没有可用串口 = 这一步根本没执行，不是通过（旧代码在这里写
                # success=True，导致 S5 永远是绿的）。skip 与 fail 要分开：
                # 没接串口是前提缺失，不是固件的问题。
                stage.success = True
                stage.verdict = "unavailable"
                stage.details = {"note": "No COM port", "skipped": True}
                stage.elapsed_ms = (time.time() - t0) * 1000
                return stage

            html_path = str(paths.runtime_dir(root) / "serial_live.html")
            self._note("Verify", f"打开串口 {port} 采样本"
                                 f"（{'断言 ' + expected[:40] if expected else '无断言，只采集'}）")
            stop_path = html_path + ".stop"
            pause_path = html_path + ".pause"
            # 面板落点可能还没建（全新工作区）：采集线程直接往里写文件，
            # 目录不存在会静默落到 exit_trace.log 里，表现为「S5 采不到数据」。
            Path(html_path).parent.mkdir(parents=True, exist_ok=True)

            # ── 回收上一轮 S5 的采集线程 ────────────────────────────────────
            # panel 常驻是产品特性（人要持续观察），代价是采集线程一直持有 COM 口。
            # 若不回收就直接开新线程：连续 10 次打开失败 → 最终被报成
            # 「串口已打开但 8s 没收到字节」，把排查引向硬件/波特率（实测发生过）。
            # 这里先叫停上一位，并等它真的关闭端口（3 s 上限）。
            prev = getattr(self, "_collector_alive", None)
            prev_stop = getattr(self, "_collector_stop_path", "")
            if prev is not None and prev.is_alive() and prev_stop:
                logger.info("S5 回收上一轮采集线程（释放 %s）", port)
                try:
                    with open(prev_stop, "w", encoding="utf-8") as f:
                        f.write("stop\n")
                except OSError as exc:
                    logger.warning("S5 无法写入上一轮 stop 文件 %s: %s", prev_stop, exc)
                prev.join(timeout=3.0)
                if prev.is_alive():
                    logger.warning("S5 上一轮采集线程 3s 内未退出，端口可能仍被占用")

            # 清掉上一次会话遗留的控制文件。留着 .stop → 采集线程进来第一轮
            # 就退出，S5 永远 0 字节；留着 .pause → 采集线程把端口关掉后死等
            # 一个永远不会来的「Open」。两种都表现为「固件没在跑」，
            # 会把人往硬件故障上引（实测踩过一次）。
            for _stale in (stop_path, pause_path):
                try:
                    os.remove(_stale)
                except OSError:
                    pass

            # Shared state between main thread and collector thread
            sample_ready = threading.Event()
            _sample_lines: list[str] = []
            _total_lines = [0]
            # 打开端口失败的原因（由采集线程回填）——见 _collector_thread 同名参数
            _open_errors: list[str] = []

            # Start collector thread (daemon — dies with MCP process)
            # 回读波特率取自板卡声明（board.yaml::serial.baudrate）。AVR 板卡
            # 未声明时回落到 9600 —— 与历史行为一致，不改变既有 AVR 结果。
            _serial_cfg = config.get("serial") or {}
            read_baud = int(_serial_cfg.get("baudrate", 9600) or 9600)
            t = threading.Thread(
                target=self._collector_thread,
                args=(html_path, port, read_baud, sample_ready, _sample_lines, _total_lines,
                      stages_summary, process_summary, _open_errors),
                daemon=True,
            )
            t.start()

            # Keep reference for run() to wait on
            self._collector_alive = t
            # 停止信号路径：panel_wait 为有限值时，run_full 必须在返回前让
            # 采集线程退出并释放 COM 口，否则下一次 flash 会因端口被占失败。
            self._collector_stop_path = stop_path

            # Wait for sample (3 lines or 8s timeout)
            if sample_ready.wait(timeout=8.0):
                sample_lines = list(_sample_lines[:3])
                total = _total_lines[0]
            else:
                sample_lines = []
                total = 0

            # 端口根本没打开：这是**前提缺失**，不是"固件没输出"。
            # 两者处置完全不同（一个去清占用、一个去查波特率/接线/固件），
            # 因此必须单独成一个 verdict，不能混进 empty。
            if _open_errors:
                stage.success = False
                stage.verdict = VERDICT_PORT_BUSY
                stage.error = (
                    f"串口 {port} 打开失败：{_open_errors[0]}。"
                    "常见原因：上一轮采集线程/面板仍持有该端口，"
                    "或另一个 ff 进程正在使用同一串口。"
                )
                stage.details = {
                    "port": port,
                    "baud": read_baud,
                    "verdict": VERDICT_PORT_BUSY,
                    "sample_lines": [],
                    "sample_count": 0,
                    "total_lines": 0,
                    "open_error": _open_errors[0],
                }
                stage.elapsed_ms = (time.time() - t0) * 1000
                logger.info("S5 Verify: %s (%s)", stage.verdict, _open_errors[0])
                return stage

            # 判定：只看机械事实，不含任何业务语义（详见 _decide_verify）。
            decision = _decide_verify(sample_lines, expected, port, read_baud)
            stage.success = decision.success
            stage.verdict = decision.verdict
            stage.error = decision.error

            stage.details = {
                "port": port,
                "baud": read_baud,
                "sample_lines": sample_lines,
                "sample_count": len(sample_lines),
                "total_lines": total,
                "verdict": decision.verdict,
            }
            if expected:
                stage.details["expected"] = expected
                if decision.pattern_match is not None:
                    stage.details["pattern_match"] = decision.pattern_match
                if decision.pattern_error:
                    stage.details["pattern_error"] = decision.pattern_error

            # Start HTTP server + write redirect (MCP persistent — panel lives)
            try:
                from firmforge.adapters.mcp_server import _start_monitor_httpd
                http_port = _start_monitor_httpd(str(root))
                if http_port:
                    goto_panel = str(paths.runtime_dir(root) / "goto_panel.html")
                    with open(goto_panel, "w", encoding="utf-8") as f:
                        f.write(f'<script>window.location.replace("http://127.0.0.1:{http_port}/serial_live.html");</script>')
                    stage.details["panel_url"] = f"http://127.0.0.1:{http_port}/serial_live.html"
                    stage.details["panel_file"] = (
                        f"{paths.RUNTIME_DIR_NAME}/goto_panel.html")
            except Exception:
                pass

        except Exception as e:
            # 这里以前是 success=True —— 连 S5 自己崩了都算通过。
            # 采不到证据就是采不到，不能因为「是工具的问题」就报绿。
            stage.success = False
            stage.verdict = "error"
            stage.error = f"Verify failed: {e}"
            stage.details = {"note": f"Verify failed: {e}", "verdict": "error"}

        stage.elapsed_ms = (time.time() - t0) * 1000
        logger.info("S5 Verify: %s (%d sample lines)",
                    stage.verdict or "?", stage.details.get("sample_count", 0))
        return stage

    @staticmethod
    def _load_serial_config(data_dir: str, default_baud: int = 9600,
                            default_parity: str = "None") -> tuple[int, str]:
        """Read <runtime>/serial_config.json (panel baud/parity), else defaults."""
        import json
        try:
            with open(os.path.join(data_dir, "serial_config.json"), encoding="utf-8") as f:
                cfg = json.load(f)
            return int(cfg.get("baud", default_baud)), str(cfg.get("parity", default_parity))
        except Exception:
            return default_baud, default_parity

    def _collector_thread(self, html_path: str, port: str, baud: int,
                          sample_ready, sample_lines_out: list, total_lines_out: list,
                          stages_info: str = "", process_info: str = "",
                          open_error_out: list | None = None) -> None:
        """Daemon thread — opens COM4, reads serial, writes HTML + signals sample.

        `open_error_out`：打开端口失败时的原因（异常文本）由这里回传主线程。
        没有它，打开失败与「端口打开了但没数据」在 S5 里长得一模一样 ——
        见下面 10 次重试那一处的注释。
        """
        try:
            import json
            from pathlib import Path

            data_dir = str(Path(html_path).parent)
            stop_path = html_path + ".stop"

            # Serial write command file (panel Serial tab)
            serial_write_file = os.path.join(data_dir, "serial_write.json")
            baud, parity = self._load_serial_config(data_dir, baud, "None")
            rx_total = [0]
            tx_total = [0]

            # Open COM4 (retry up to 10x — avrdude may still be releasing port)
            from firmforge.providers.com_port import ComPort
            ser_wrapper = None
            last_open_err = ""
            for _retry in range(10):
                try:
                    ser_wrapper = ComPort(port, baud, timeout=0.3, parity=parity)
                    ser_wrapper.__enter__()
                    break
                except Exception as exc:
                    # 记下最后一次的真实原因。最常见的两条：
                    #   PermissionError / "拒绝访问"  → 端口被别的进程持有
                    #   FileNotFoundError            → 端口消失（拔线 / 驱动未装）
                    # 这两条与「打开了但没数据」的处置完全不同，不能合并成一句话。
                    last_open_err = f"{type(exc).__name__}: {exc}"
                    time.sleep(0.5)
            if ser_wrapper is None:
                if open_error_out is not None:
                    open_error_out.append(last_open_err or "unknown")
                # Write crash log but don't crash MCP
                with open(os.path.join(data_dir, "exit_trace.log"), "a") as f:
                    f.write(f"[{time.strftime('%H:%M:%S')}] EXIT: Could not open {port}"
                            f" ({last_open_err})\n")
                sample_ready.set()  # Signal so verify doesn't hang
                return

            ser = ser_wrapper.ser

            # 先丢掉「打开之前」残留在驱动缓冲里的字节（上一轮遗留），再开始接收。
            # 🔴 这一步必须在 settle **之前**做。放在 settle 之后会把 settle 期间
            #    收到的数据整段丢弃 —— S4 刚烧录、目标复位并打印上电日志的正是那段
            #    时间窗（约 200 B，115200 下 2 ms 发完）。原顺序（sleep 2 s 再 reset）
            #    造成过「S4 确实烧录成功、S5 却报 8 s 没收到字节」的误导结论。
            try:
                ser.reset_input_buffer()
            except Exception:
                pass
            # settle 只保「固件复位后的首帧」，不做缓冲清空。
            # 500 ms 足够 HSE/PLL/VOS 起振 + 首行输出，且不侵占 8 s 采样窗。
            time.sleep(0.5)

            buf = ""
            _sample_written = False
            _sample_timeout = 8.0
            # 零字节时的宽限：一个字节都不来的固件，多等 7 秒不会变出第一行。
            _no_data_grace = 1.5
            last_write = time.time()
            _start_time = time.time()
            lines: list[str] = []
            pause_path = os.path.join(data_dir, "serial_live.html.pause")

            html = _render_panel(port, baud, lines, 0, 0,
                                 not os.path.exists(pause_path),
                                 stages_info, process_info)
            try:
                with open(html_path, "w", encoding="utf-8") as f:
                    f.write(html)
            except Exception:
                pass

            while True:
                # Check .stop (full exit — Stop button or tab close)
                if os.path.exists(stop_path):
                    break

                # Check .pause (COM4 close — Close button on panel)
                if os.path.exists(pause_path):
                    # Close COM4 gracefully
                    try: ser.close()
                    except Exception: pass
                    try: ser_wrapper.__exit__(None, None, None)
                    except Exception: pass
                    ser = None
                    # Wait for .pause to be removed (Open button)
                    while os.path.exists(pause_path):
                        if os.path.exists(stop_path):
                            break
                        time.sleep(0.3)
                    if os.path.exists(stop_path):
                        break
                    # Reopen COM4 (read latest panel baud/parity config)
                    ser_wrapper = None
                    baud, parity = self._load_serial_config(data_dir, baud, parity)
                    for _retry2 in range(10):
                        try:
                            ser_wrapper = ComPort(port, baud, timeout=0.3, parity=parity)
                            ser_wrapper.__enter__()
                            break
                        except Exception:
                            time.sleep(0.5)
                    if ser_wrapper is None:
                        break
                    ser = ser_wrapper.ser
                    try: ser.reset_input_buffer()
                    except Exception: pass
                    lines.clear()  # don't accumulate old data on reopen
                    rx_total[0] = 0; tx_total[0] = 0
                    continue

                # Process send command (from panel input)
                _sc = _exec_serial_write(serial_write_file, ser, tx_total)
                if _sc:
                    lines.append(_sc)

                # Process MODBUS command (atomic — response via queue)
                _exec_modbus(ser, tx_total, rx_total)

                # Sample handoff — write first 3+ lines to shared list, signal parent
                if not _sample_written:
                    # 一个字节都没收到就不等满 8 s：空输出的固件永远不会变出第一行，
                    # 早退把每次"固件没输出"的诊断从 8 s 压到 1.5 s。判定依据是
                    # **收到的字节数**而不是行数 —— 固件只打了不带换行的半截内容时
                    # lines 也是空的，那种情况不该提前放弃。
                    _grace = _sample_timeout if rx_total[0] else _no_data_grace
                    if len(lines) >= 3 or (time.time() - _start_time > _grace):
                        if rx_total[0] == 0:
                            logger.info("S5 采样：%.1fs 内零字节，提前判定无输出"
                                        "（不等满 %.0fs）", _no_data_grace, _sample_timeout)
                        sample_lines_out.extend(lines[:3] if lines else [])
                        total_lines_out[0] = len(lines)
                        try:
                            sample_ready.set()
                        except Exception:
                            pass
                        _sample_written = True

                # Read serial
                try:
                    chunk = ser.read(64)
                except Exception:
                    time.sleep(0.5)
                    continue

                if chunk:
                    rx_total[0] += len(chunk)
                    if isinstance(chunk, bytes):
                        chunk = chunk.decode("ascii", errors="replace")
                    buf += chunk
                    while chr(10) in buf:
                        line, buf = buf.split(chr(10), 1)
                        line = line.rstrip(chr(13))
                        if line:
                            lines.append(line)

                # Write HTML (throttled: max 3.3 fps)
                now = time.time()
                if now - last_write >= 0.3:
                    html = _render_panel(port, baud, lines, rx_total[0], tx_total[0],
                                         not os.path.exists(pause_path),
                                         stages_info, process_info)
                    try:
                        with open(html_path, "w", encoding="utf-8") as f:
                            f.write(html)
                    except Exception:
                        pass
                    last_write = now

                # Push to SSE stream (instant updates, zero polling latency)
                _sse_pushed = getattr(ser, '_sse_pushed', 0)
                if _sse_pushed < len(lines):
                    try:
                        from firmforge.adapters.mcp_server import _get_stream_queue
                        _get_stream_queue().put_nowait({
                            "new": lines[_sse_pushed:],  # delta only
                            "total": len(lines),
                            "rx": rx_total[0],
                            "tx": tx_total[0],
                            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                            "stages": stages_info,
                        })
                        setattr(ser, '_sse_pushed', len(lines))
                    except Exception:
                        pass

                time.sleep(0.05)

            # Cleanup: close COM4 gracefully
            try:
                ser.close()
            except Exception:
                pass
            try:
                ser_wrapper.__exit__(None, None, None)
            except Exception:
                pass

            # Clear stream queue so SSE handler exits
            try:
                from firmforge.adapters.mcp_server import _clear_stream_queue
                _clear_stream_queue()
            except Exception:
                pass

        except Exception as e:
            # Thread crash — log but don't kill MCP process
            try:
                import traceback
                log_dir = str(Path(html_path).parent) if html_path else paths.RUNTIME_DIR_NAME
                with open(os.path.join(log_dir, "exit_trace.log"), "a") as f:
                    f.write(f"[{time.strftime('%H:%M:%S')}] EXIT: THREAD CRASH {type(e).__name__}: {e}\n")
                    f.write(traceback.format_exc())
            except Exception:
                pass
            try:
                sample_ready.set()
            except Exception:
                pass


# -- MODBUS + Panel helpers (module-level, shared by collector thread) --

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

_PANEL_TEMPLATE = None


def _render_panel(port, baud, lines, rx_count, tx_count, is_open, stages_str="", process_str=""):
    global _PANEL_TEMPLATE
    if _PANEL_TEMPLATE is None:
        _tp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools", "panel.html")
        with open(_tp, encoding="utf-8") as f:
            _PANEL_TEMPLATE = f.read()
    rows = "".join(f'<div class="line">{ln}</div>\n' for ln in lines)
    t = _PANEL_TEMPLATE
    t = t.replace("{{PORT}}", str(port))
    t = t.replace("{{OPEN_CLOSE}}", "Close" if is_open else "Open")
    t = t.replace("{{DOT_COLOR}}", "var(--acc)" if is_open else "var(--warn)")
    t = t.replace("{{ROWS}}", rows)
    t = t.replace("{{RX}}", str(rx_count))
    t = t.replace("{{TX}}", str(tx_count))
    t = t.replace("{{IS_OPEN}}", "true" if is_open else "false")
    t = t.replace("{{STAGES}}", stages_str)
    t = t.replace("{{PROCESS}}", process_str)
    return t


def _exec_serial_write(send_file, ser, tx_total):
    if not os.path.exists(send_file): return None
    try:
        import json
        with open(send_file, "rb") as f: data = json.loads(f.read())
        os.remove(send_file)
        text = data.get("text", ""); is_hex = data.get("hex", False); crlf = data.get("crlf", True)
        payload = bytes.fromhex(text.replace(" ","")) if is_hex else text.encode("ascii","replace")
        if crlf: payload += b"\r\n"
        ser.write(payload); tx_total[0] += len(payload)
        return f'<span style="color:var(--tx-clr)">[TX]</span> {text}'
    except: return None


def _exec_modbus(ser, tx_total, rx_total):
    import queue as _queue
    from firmforge.adapters.panel_service import get_modbus_request_queue, get_modbus_response_queue
    req_q = get_modbus_request_queue()
    resp_q = get_modbus_response_queue()
    try:
        data = req_q.get(block=False)
    except _queue.Empty:
        return
    if ser is None:
        resp_q.put({"error": "serial closed — open COM first", "crc_ok": False,
                    "regs": [], "rx_bytes": 0, "tx_bytes": 0})
        return
    try:
        import struct, time
        from firmforge.tools.modbus_utils import modbus_encode_frame, modbus_crc
        def _mb_int(s, default=0):
            """Parse decimal or 0x-prefixed hex; fall back to default on error."""
            try:
                s = str(s).strip()
                return int(s, 16) if s.lower().startswith("0x") else int(s, 10)
            except (ValueError, TypeError):
                return default

        mb = data.get("mb", {})
        slave = _mb_int(mb.get("slave", 1), 1); fc = _mb_int(mb.get("fc", 3), 3)
        addr = _mb_int(mb.get("addr", 0)); count = _mb_int(mb.get("count", 1), 1)
        ds = mb.get("data", "")
        # Parameter validation
        if not (1 <= slave <= 247):
            resp_q.put({"error": f"slave {slave} out of range (1-247)", "crc_ok": False,
                        "regs": [], "rx_bytes": 0, "tx_bytes": 0})
            return
        if not (0 <= addr <= 0xFFFF):
            resp_q.put({"error": f"addr {addr} out of range (0-65535)", "crc_ok": False,
                        "regs": [], "rx_bytes": 0, "tx_bytes": 0})
            return
        vs = []
        if fc in (6, 16) and ds:
            import re as _re
            vs = [_mb_int(v) for v in _re.split(r"[\s,，]+", ds.strip()) if v.strip()]
        frame = modbus_encode_frame(slave, fc, addr, count, vs)
        ser.write(frame); tx_total[0] += len(frame)
        time.sleep(0.05)  # wait for slave to receive + respond (~20ms)
        resp = b""
        try:
            resp = ser.read(256)
        except Exception:
            resp = b""
        rx_total[0] += len(resp)
        rh = " ".join(f"{b:02X}" for b in resp) if resp else "(no response)"
        ok = False
        regs = []
        if len(resp) >= 5 and modbus_crc(resp[:-2]) == struct.unpack("<H", resp[-2:])[0]:
            ok = True
            if fc in (3, 4):
                bc = resp[2]
                regs = [resp[i] << 8 | resp[i + 1] for i in range(3, min(3 + bc, len(resp) - 2), 2)]
        resp_q.put({"raw": rh if ok else rh + ' <span style="color:var(--warn)">CRC ERR</span>',
                    "crc_ok": ok, "regs": regs, "rx_bytes": len(resp), "tx_bytes": len(frame)})
        # Push counter update to SSE (modbus doesn't append to lines)
        try:
            from firmforge.adapters.mcp_server import _get_stream_queue
            _get_stream_queue().put_nowait({
                "new": [], "rx": rx_total[0], "tx": tx_total[0],
                "ts": time.strftime("%Y-%m-%d %H:%M:%S")
            })
        except Exception:
            pass
    except Exception as e:
        resp_q.put({"error": str(e), "crc_ok": False, "regs": [],
                    "rx_bytes": 0, "tx_bytes": 0})


