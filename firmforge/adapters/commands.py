"""Shared command implementations for the CLI and MCP adapters.

架构契约：两个入口层驱动**同一份**编排与序列化，各自只保留真正属于自己的东西：
  - CLI（cli.py）：argparse、人类可读输出、退出码
  - MCP（mcp_server.py）：工具 schema（docstring）、注册、stdio transport

历史上 8 个命令在两边各写一遍编排，还各自维护一套 JSON 序列化（形状不一致：
`ff run --json` 与 MCP `ff_run` 对同一操作返回不同结构）。现在：
  - run_pipeline()：唯一的流水线执行核心（run/build/review/verify/flash 共用）
  - detect_payload()/stages_payload()/result_payload()/flash_payload()：唯一的序列化
  - do_*()：MCP 工具入口（执行 + 序列化 + 异常转 error dict）

异常约定：run_pipeline() 让异常向上抛 —— 两个 adapter 按各自的契约兜底
（CLI：main() 顶层落成 error 帧；MCP：do_*() 里转成 error dict）。
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger("firmforge.commands")


def _add_project_root_to_path() -> Path:
    root = str(Path(__file__).resolve().parent.parent.parent)
    if root not in sys.path:
        sys.path.insert(0, root)
    return Path(root)


# -- Pipeline execution core (shared by every stage command) --

def run_pipeline(
    *,
    mode: str = "run",
    board: str = "",
    app: str = "",
    expected: str = "",
    firmware: str = "",
    app_name: str = "",
    workspace: str = "",
    boards_dir: str | Path | None = None,
    panel_open: str = "none",
    panel_wait: float = 0,
    progress_callback: Callable[[str, bool, dict, str | None], None] | None = None,
    on_note: Callable[[str, str], None] | None = None,
):
    """Execute the pipeline for one stage command. Returns PipelineResult.

    mode ∈ {"run", "build", "review", "verify", "flash"}：
      run    → Detect → Review → Build → Flash → Verify（端到端）
      build  → Detect → Review → Build（stop_after，无硬件）
      review → 只跑 S2
      verify → 只跑 S5（支持面板参数）
      flash  → 只跑 S4（firmware/app_name 按构建缓存解析）

    工作区统一走 paths.resolve_workspace（显式 > FIRMFORGE_WORKSPACE > cwd）。
    """
    from firmforge.core.pipeline_runner import PipelineRunner
    from firmforge.infrastructure import paths

    runner = PipelineRunner(
        boards_dir=boards_dir,
        workspace=str(paths.resolve_workspace(workspace)),
        on_note=on_note,
    )
    board_id = board or None

    if mode == "build":
        return runner.build(source_dir=app or None, board_id=board_id,
                            progress_callback=progress_callback)
    if mode == "review":
        return runner.run_full(source_dir=app, board_id=board_id,
                               only=("review",),
                               progress_callback=progress_callback)
    if mode == "verify":
        return runner.run_full(board_id=board_id, expected=expected,
                               only=("verify",),
                               panel_open=panel_open, panel_wait=panel_wait,
                               progress_callback=progress_callback)
    if mode == "flash":
        return runner.run_full(board_id=board_id, only=("flash",),
                               firmware=firmware, app_name=app_name,
                               progress_callback=progress_callback)
    # mode == "run"
    return runner.run_full(source_dir=app or None, board_id=board_id,
                           expected=expected,
                           panel_open=panel_open, panel_wait=panel_wait,
                           progress_callback=progress_callback)


# -- Canonical serializers (the ONE shape for both adapters) --

def stages_payload(result) -> list[dict[str, Any]]:
    """PipelineStage 列表 → 对外 JSON。run / build / review 共用这一份。

    以前 build 与 run 各写一遍序列化，于是 Review 段的 cppcheck / warnings /
    confidence 只在 run 里出现 —— 单跑 `ff review` 拿不到该看的东西，
    而两份代码谁也不会因为另一份漏字段而报警。
    """
    out: list[dict[str, Any]] = []
    for s in result.stages:
        info: dict[str, Any] = {
            "stage": s.stage, "name": s.name, "success": s.success,
            "elapsed_ms": round(s.elapsed_ms, 0),
        }
        if s.error:
            info["error"] = s.error[:200]
        if s.details.get("sub_stages"):
            info["sub_stages"] = s.details["sub_stages"]
        if s.name == "Review":
            info["cppcheck"] = s.details.get("cppcheck", [])
            info["warnings"] = s.details.get("warnings", [])
            if s.details.get("review_counts"):
                info["review_counts"] = s.details["review_counts"]
            if s.details.get("confidence"):
                info["confidence"] = s.details["confidence"]
        if s.name == "Build" and s.details.get("compile_rounds", 0) > 0:
            info["compile_rounds"] = s.details["compile_rounds"]
        if s.name == "Verify":
            # verdict 是 S5 的结局：verified / mismatch / collected / empty /
            # unavailable。只有 verified 算通过；collected 表示采到了数据但
            # 调用方没给断言，需要 Agent 自己判断。
            info["verdict"] = getattr(s, "verdict", "") or ""
            info["sample_lines"] = s.details.get("sample_lines", [])
            info["matched_baud"] = s.details.get("matched_baud", 0)
            # 全文只有开面板时才有（面板关了就不留一份全文）。别把「没有全文」
            # 序列化成空串当成「串口没输出」—— 拿不到就不给这个字段。
            full = s.details.get("serial_output", "")
            if full:
                info["serial_output"] = full[:200]
            if "pattern_match" in s.details:
                info["pattern_match"] = s.details["pattern_match"]
                info["expected"] = s.details.get("expected", "")
                info["actual"] = s.details.get("actual", "")[:200]
            if "panel_url" in s.details:
                info["panel_url"] = s.details["panel_url"]
                info["panel_file"] = s.details["panel_file"]
        out.append(info)
    return out


def result_payload(result) -> dict[str, Any]:
    """一次流水线运行的通用结果帧。"""
    return {
        "overall_success": result.overall_success,
        "board": result.board,
        "total_elapsed_ms": round(result.total_elapsed_ms, 0),
        "stages": stages_payload(result),
    }


def flash_payload(result) -> dict[str, Any]:
    """Flash 命令的结果帧（CLI `ff flash --json` 与 MCP `ff_flash` 共用）。"""
    s4 = next((s for s in result.stages if s.name == "Flash"), None)
    return {
        "success": bool(result.overall_success),
        "board": result.board,
        "firmware": (s4.details.get("firmware_path", "") if s4 else ""),
        "bytes_written": (s4.details.get("bytes_written", 0) if s4 else 0),
        "elapsed_ms": round(result.total_elapsed_ms),
        "error": (s4.error if s4 and not s4.success else ""),
        "candidates": (s4.details.get("candidates", []) if s4 else []),
        "stages": stages_payload(result),
    }


def detect_payload(detector, result) -> dict[str, Any]:
    """结构化 detect 结果（CLI 与 MCP 共用；detector/result 由调用方持有）。"""
    board_config = None
    if result.board_id:
        board_config = detector.resolve_board(result.board_id) or None
    return {
        "board_id": result.board_id,
        "boards": result.boards,
        "detected": bool(result.board_id),
        "candidates": [
            {
                "board_id": c.board_id,
                "confidence": c.confidence,
                "source": c.source,
                "details": c.details,
            }
            for c in result.candidates
        ],
        # 探测失败的说明（探针在位但目标无响应 / DEV_ID 不符）。
        # 与 candidates 分开：这些不是候选，是"哪些结论不能下"。
        "notes": getattr(result, "notes", []) or [],
        "board_config": board_config,
    }


# -- Tool implementations (MCP entry points; CLI reuses the payload fns) --

def do_detect(intent: str = "", boards_dir: str = "") -> dict[str, Any]:
    """Execute ff_detect."""
    try:
        from firmforge.core.board_detector import BoardDetector
        detector = BoardDetector(boards_dir=boards_dir or None)
        result = detector.detect(user_text=intent)
        return detect_payload(detector, result)
    except Exception as e:
        return {"error": str(e), "detected": False, "boards": [], "candidates": []}


#: ``ff context`` 的主题别名。主题是**枚举**，不是关键字 ——
#: 早先实现把 ``--topic registers`` 当成「在寄存器名里搜 registers」，
#: 于是这个最该用的主题永远返回 0 条，而错误是静默的（没有异常，只有空表）。
_TOPIC_ALIASES: dict[str, str] = {
    "": "all", "all": "all", "overview": "all",
    "registers": "registers", "register": "registers",
    "reg": "registers", "regs": "registers",
    "pins": "pins", "pin": "pins",
    "baud": "baud", "baudrate": "baud", "baud_rate": "baud",
}

#: 概览时寄存器条目的返回上限。超过就瘦身（去掉位域表）并标记 truncated。
_REG_PREVIEW_LIMIT = 20


def _public_register(entry: dict[str, Any], keep_fields: bool = True
                     ) -> dict[str, Any]:
    """知识库内部条目 → 对外条目。

    内部字段带 ``_`` 前缀（``_group`` / ``_platform``），是索引期的记账信息。
    对外只暴露干净的 ``group`` 键，调用方不必知道索引长什么样。位域表默认
    保留，只有条数过多时才丢 —— 2955 条寄存器全带 ``fields`` 是 3 MB 的
    payload，那是给程序读的，不是给 ``ff context`` 的输出。
    """
    out = {k: v for k, v in entry.items() if not k.startswith("_")}
    out["group"] = entry.get("_group")
    if not keep_fields:
        out.pop("fields", None)
    return out


def do_context(board: str = "", topic: str = "") -> dict[str, Any]:
    """Execute ff_context — return board register/pin/baud reference.

    输出形状对所有板卡一致，字段取值一律走 ``core.board_view`` —— 板卡声明
    里 ``specs.flash`` / ``specs.clock`` 是字符串（``"2 MB"`` / ``"480 MHz"``），
    而这里要给的是字节数和赫兹。此前直接读 ``mcu.flash_size``（这个字段
    三块板卡都没有），导致 AVR 与 STM32 的 Flash 都显示 0。
    """
    try:
        from firmforge.core.board_view import board_pin_list, board_specs
        from firmforge.knowledge.knowledge_base import KnowledgeBase
        from firmforge.core.board_detector import BoardDetector

        if not board:
            detector = BoardDetector()
            detect_result = detector.detect()
            board = detect_result.board_id or ""

        if not board:
            return {"error": "No board detected or specified. Run ff_detect first."}

        config = BoardDetector().resolve_board(board) or {}
        if not config:
            return {"error": f"Board '{board}' not found in board definitions."}

        specs = board_specs(config)
        knowledge_base = KnowledgeBase()
        knowledge_base.load_for_board(config)

        raw_topic = (topic or "").strip()
        wanted = _TOPIC_ALIASES.get(raw_topic.lower(), "query")

        payload: dict[str, Any] = {
            **specs,
            "features": config.get("features", {}),
            "topic": raw_topic or None,
            "topic_mode": wanted,
            "registers": [],
            "register_groups": {},
            "registers_truncated": False,
            "pins": {"format": "none", "count": 0, "items": []},
        }

        # ----- 寄存器 ------------------------------------------------------
        if wanted == "query":
            hits, truncated = knowledge_base.search_registers(raw_topic)
            payload["registers"] = hits[:200]
            payload["registers_truncated"] = truncated or len(hits) > 200
        elif wanted in ("all", "registers"):
            all_regs = knowledge_base.get_all_registers()
            payload["register_groups"] = knowledge_base.register_groups()
            payload["register_total"] = sum(payload["register_groups"].values())
            payload["registers"] = list(all_regs.values())[:_REG_PREVIEW_LIMIT]
            payload["registers_truncated"] = (
                payload["register_total"] > _REG_PREVIEW_LIMIT)

        # 映射只做一次。此前 query 分支与瘦身分支各映射一遍，第二遍拿不到
        # 已经被抹掉的 ``_group``，结果 36 条同名 CR1 全显示成 ``CR1`` ——
        # 有数据但分不清属于哪个外设。
        keep_fields = len(payload["registers"]) <= _REG_PREVIEW_LIMIT
        if payload["registers"]:
            payload["registers"] = [_public_register(r, keep_fields=keep_fields)
                                    for r in payload["registers"]]

        # ----- 引脚 --------------------------------------------------------
        pin_map = (knowledge_base.get_pin_map(board)
                   if specs.get("chip_key") else None)
        if wanted in ("all", "pins"):
            fmt, items = board_pin_list(config, pin_map)
            payload["pins"] = {"format": fmt, "count": len(items),
                               "items": items}

        # ----- 波特率 ------------------------------------------------------
        if wanted == "baud":
            presets = (pin_map or {}).get("baud_rate_presets", {})
            payload["baud"] = presets
            if not presets:
                payload["baud_note"] = (
                    "该板卡没有波特率预设表：STM32 的波特率由 PCLK 与 BRR "
                    "算出，不是查表能得到的常数。")

        payload["origin"] = knowledge_base.reference_origin(specs.get("library"))
        return payload
    except Exception as e:
        return {"error": str(e), "board": board or "unknown"}


def do_build(board: str = "", app: str = "", workspace: str = "") -> dict[str, Any]:
    """Execute ff_build — Review + Build only."""
    try:
        result = run_pipeline(mode="build", board=board, app=app,
                              workspace=workspace)
    except Exception as e:
        return {"overall_success": False, "error": str(e), "stages": []}

    return result_payload(result)


def do_run(board: str = "", app: str = "", expected: str = "",
           workspace: str = "") -> dict[str, Any]:
    """Execute ff_run: Detect → Review → Build → Flash → Verify.

    工作区必须是**调用方的工作区**，不是工具自己的安装目录。
    状态（.ff-run/state.json）、面板（serial_live.html）、串口配置
    （serial_config.json）三者都要落在同一处，否则会出现「状态在这里、
    面板在那里」，串口参数还会被别的会话串改（实测误判过一次）。
    """
    progress_events: list[dict[str, Any]] = []

    def _on_progress(stage_name: str, success: bool,
                     details: dict, error: str | None) -> None:
        progress_events.append({
            "stage": stage_name,
            "success": success,
            "details": details,
            "error": error[:200] if error else None,
        })

    try:
        result = run_pipeline(
            mode="run", board=board, app=app, expected=expected,
            workspace=workspace,
            progress_callback=_on_progress,
            # MCP 调用没有「人在面板前」这回事。默认值本来就是「全关」
            # （panel_open="none" + panel_wait=0），这里显式写出来，是为了让
            # 「MCP 永远不碰面板」成为读得到的事实，而不是要靠猜默认值。
            # 面板文件仍在 stage.details 里（panel_url / panel_file），
            # 需要实时看的人自己调用 ff_monitor 或打开那个文件。
            panel_open="none",
            panel_wait=0,
        )
    except Exception as e:
        return {"overall_success": False, "error": str(e), "stages": [],
                "progress": progress_events}

    payload = result_payload(result)
    payload["progress"] = progress_events

    # 串口证据：与 `ff_verify` 共用 `serial_evidence`，两个入口不许给两种答案。
    s5 = next((s for s in result.stages if s.name == "Verify"), None)
    payload["serial_lines"] = serial_evidence(s5)
    if s5 is not None and "panel_url" in s5.details:
        payload["panel_url"] = s5.details["panel_url"]
        payload["panel_file"] = s5.details["panel_file"]
    return payload


def do_flash(board: str = "", firmware: str = "", workspace: str = "",
             build: str = "") -> dict[str, Any]:
    """Execute ff_flash — 走 run_full(only=("flash",))，与 `ff flash` 同一入口。

    以前这里调 `PipelineRunner.flash()`，那条路**不读写 `.ff-run/state.json`**：
    MCP 烧完之后 `ff run` 仍认为没烧过，会再烧一遍，而两次之间没人被告知。
    CLI 侧修过一次，MCP 侧当时漏了 —— 所以现在两边都走 run_full。
    """
    try:
        result = run_pipeline(mode="flash", board=board, firmware=firmware,
                              app_name=build, workspace=workspace)
    except Exception as e:
        return {"success": False, "error": str(e), "firmware": firmware}

    return flash_payload(result)


def do_review(board: str = "", app: str = "", workspace: str = "") -> dict[str, Any]:
    """Execute ff_review — 只跑 S2（静态分析 + 寄存器审查 + 置信度）。"""
    if not app:
        return {"overall_success": False, "error": "app is required", "stages": []}

    try:
        result = run_pipeline(mode="review", board=board, app=app,
                              workspace=workspace)
    except Exception as e:
        return {"overall_success": False, "error": str(e), "stages": []}
    return result_payload(result)


def serial_evidence(stage) -> list[str]:
    """一个 Verify 阶段的串口证据，按行给。

    优先完整输出（只有开面板时才有全文），否则退回 S5 至少 3 条采样行。
    **两个入口必须走同一个函数** —— 否则「ff_run 说 verified 但一行数据都没有」
    这种自相矛盾会再次出现（2026-10-28 实测：run 读一个已停写的字段，
    verify 读 sample_lines，同一个阶段两种答案）。
    """
    if stage is None:
        return []
    full = stage.details.get("serial_output", "")
    if full.strip():
        return full.splitlines()
    return list(stage.details.get("sample_lines", []))


def do_verify(board: str = "", expected: str = "",
              workspace: str = "") -> dict[str, Any]:
    """Execute ff_verify — 只跑 S5（开串口采样本 / 检查断言）。

    MCP 调用不碰面板：没有人在屏幕前点 Stop，起了也不会有人看。
    """
    try:
        result = run_pipeline(mode="verify", board=board, expected=expected,
                              workspace=workspace,
                              panel_open="none", panel_wait=0)
    except Exception as e:
        return {"overall_success": False, "error": str(e), "stages": []}

    payload = result_payload(result)
    s5 = next((s for s in result.stages if s.name == "Verify"), None)
    payload["verdict"] = (getattr(s5, "verdict", "") if s5 else "") or ""
    payload["serial_lines"] = serial_evidence(s5)
    return payload


def do_status(workspace: str = "") -> dict[str, Any]:
    """Execute ff_status — 读 `.ff-run/state.json`，回答「下次会跳过什么、为什么」。"""
    from firmforge.core.pipeline_state import PipelineState
    from firmforge.infrastructure import paths

    # 传了 workspace 就用它（CLI 总是传 "." 或 --workspace）；
    # 没传才去读 FIRMFORGE_WORKSPACE / cwd —— 与 do_run 的解析规则一致，
    # 否则 MCP 的 run 与 status 会指向两个不同的 .ff-run/。
    root = (Path(workspace).resolve() if workspace
            else paths.resolve_workspace(""))
    state = PipelineState(root)
    data = state.data or {}
    fps = data.get("fingerprints", {}) or {}
    return {
        "workspace": str(root),
        "runtime_dir": str(paths.runtime_dir(root)),
        "fingerprints": fps,
        "stages": {name: state.stage_status(name)
                   for name in ("detect", "review", "build", "flash", "test")},
        "last_error": data.get("last_error"),
        # 「最近一次真正成功的是谁、什么时候」。last_error 被成功后擦掉，
        # 单看它只能得出「没记录错误」，看不出这份 state 是否刚跑通过。
        "last_success": data.get("last_success"),
        "skip_rules": {
            "build": "源码 + 板卡指纹不变 → 跳过，复用上次 hex",
            "flash": "源码/固件/端口/板卡全不变 → 跳过；给了 expected 一律真烧",
            "verify": "同上 → 跳过；给了 expected 一律重验",
            "review": "不跳过（cppcheck 自己按内容哈希缓存）",
        },
        "raw": data,
    }


def _stm32_board_ids(boards_dir: str = "") -> list[str]:
    """板卡目录里所有 platform == stm32 的 board_id。"""
    import yaml
    from firmforge.core.resources import boards_dir as default_boards_dir

    root = Path(boards_dir) if boards_dir else Path(default_boards_dir())
    out: list[str] = []
    for path in sorted(root.glob("*/board.yaml")):
        try:
            cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:                     # noqa: BLE001 — 坏 yaml 不阻塞扫描
            continue
        if cfg.get("platform") == "stm32":
            out.append(cfg.get("board_id") or path.parent.name)
    return out


def do_inspect(board: str = "", build: str = "", elf: str = "", pc: int | None = None,
               sym: list[str] | None = None, sym_glob: list[str] | None = None,
               periph: list[str] | None = None, no_where: bool = False,
               no_resume: bool = False, watchdog_run: bool = False,
               clear_reset_flags: bool = False, symbol_notes: str = "",
               timeout: float = 90.0, boards_dir: str = "") -> dict[str, Any]:
    """Execute ff_inspect — 只读观测（复位原因 / PC / 变量 / 外设寄存器，STM32+SWD）。

    这里只把参数变成一次观测请求并返回 payload；渲染归 CLI，字段名归 MCP。
    前置条件不成立（板卡不明 / 平台不对 / 参数互相矛盾）一律返回 error，
    **不产出半份观测** —— 半份数据的危害是它看起来像完整答案。
    """
    from firmforge.core.board_detector import BoardDetector
    from firmforge.providers.stm32.inspect import InspectRequest
    from firmforge.providers.stm32.inspect import inspect as run_inspect

    board_id = board
    if not board_id:
        # 缺省只在「唯一一台 STM32」时才自动选；多台一律要求显式，不猜。
        stm32 = _stm32_board_ids(boards_dir)
        if len(stm32) != 1:
            return {"error": (f"需要显式指定板卡（候选："
                              f"{', '.join(stm32) or '无 STM32 板卡'}）")}
        board_id = stm32[0]

    detector = BoardDetector(boards_dir=boards_dir or None)
    config = detector.resolve_board(board_id)
    if not config:
        return {"error": f"board '{board_id}' not found"}

    platform = config.get("platform", "arduino")
    if platform != "stm32":
        return {"error": (f"inspect 目前只实现 STM32（SWD 探针 + halt 读内存）。"
                          f"板卡 {board_id} 的平台是 {platform}。")}

    if pc is not None:
        # --pc 是**离线**路径：只做 addr2line，不连探针。和读内存的选项一起用
        # 会产生矛盾的数据包（一边说"没连板子"，一边给出变量值）。不静默忽略。
        clash = [flag for flag, val in (("--symbol", sym), ("--symbol-glob", sym_glob),
                                        ("--peripheral", periph)) if val]
        if clash:
            return {"error": (f"pc 是离线模式（只解析源码位置，不连探针），"
                              f"不能与 {' / '.join(clash)} 同用。"
                              f"要同时读板上变量，去掉 pc 跑在线模式；"
                              f"只想查这一行，去掉那几个参数。")}

    req = InspectRequest(
        elf=elf or None,
        app=build or None,
        pc=pc,
        symbols=list(sym or []),
        sym_globs=list(sym_glob or []),
        peripherals=list(periph or []),
        where=not no_where,
        resume=not no_resume,
        freeze_watchdog=not watchdog_run,
        clear_reset_flags=clear_reset_flags,
        symbol_notes=symbol_notes or None,
        timeout=float(timeout or 90.0),
    )
    return run_inspect(config, req)


def _hex_addr(text: str) -> int:
    """地址按十六进制解析（与 CLI 的 --pc 同一规则）。

    不收十进制：`"800"` 在不同人脑子里分别是 800 和 0x800，地址没有十进制写法。
    """
    t = str(text).strip().replace("_", "")
    if t[:2].lower() == "0x":
        t = t[2:]
    return int(t, 16)


def do_monitor(port: str = "", baud: int = 9600,
               action: str = "start", workspace: str = "") -> dict[str, Any]:
    """Start/stop serial monitor + HTTP panel.

    start/panel: start HTTP server + write goto_panel.html redirect page.
    stop: signal collector to exit + clean close port.
    （collector 始终由 S5 Verify 启动，ff_monitor 只提供 HTTP 服务与停止信号。）
    """
    from pathlib import Path
    import time
    from firmforge.infrastructure import paths
    # 面板服务的根 = 调用方工作区（与 ff_run 的 state.json 同一处）。
    root = paths.resolve_workspace(workspace)
    html_path = str(paths.runtime_dir(root) / "serial_live.html")

    if action == "stop":
        stop_file = html_path + ".stop"
        try:
            Path(stop_file).touch()
            time.sleep(3)  # collector detects .stop → os._exit(0) → COM4 released by OS
            Path(stop_file).unlink(missing_ok=True)
        except Exception:
            pass
        return {"status": "stopped"}

    if action in ("start", "panel"):
        # Auto-detect port if needed (for stop/status, port is optional)
        if not port:
            try:
                from firmforge.core.board_detector import BoardDetector
                bd = BoardDetector()
                result = bd.detect()
                for c in (result.candidates or []):
                    p = c.details.get("port", "")
                    if p and p.upper().startswith("COM"):
                        port = p
                        break
            except Exception:
                pass
        if not port:
            return {"status": "error", "message": "port required"}

        # Collector is ALWAYS started by S5 Verify — never by ff_monitor.
        # ff_monitor only provides: HTTP server + stop signal + redirect page.

        # Start HTTP server (singleton, MCP-persistent)
        from firmforge.adapters.panel_service import start_panel_httpd, write_goto_panel
        http_port = start_panel_httpd(str(root))

        # Write redirect page (shared impl with pipeline_runner S5 panel mode)
        if http_port:
            write_goto_panel(str(root), http_port)

        return {
            "status": "started", "port": port, "baud": baud,
            "panel_url": f"http://127.0.0.1:{http_port}/serial_live.html" if http_port else "",
            "panel_file": f"{paths.RUNTIME_DIR_NAME}/goto_panel.html",
            "data_file": f"{paths.RUNTIME_DIR_NAME}/serial_live.html",
        }

    return {"status": "error", "message": f"unknown action: {action}"}
