"""MCP Server Adapter — FirmForge MCU code verification toolchain.

Exposes one MCP tool per CLI subcommand that an Agent can meaningfully drive
（`ff_setup` 除外 —— 装工具链是人在装机时做的一次性动作）:

  - ff_detect:  Scan connected MCU boards
  - ff_context: Return board-specific register/pin/baud reference
  - ff_build:   Review + Build only (no hardware)
  - ff_review:  S2 only — static analysis + register review
  - ff_run:     Detect → Review → Build → Flash → Verify (full hardware pipeline)
  - ff_flash:   S4 only — flash a pre-built firmware
  - ff_verify:  S5 only — open serial port and check the assertion
  - ff_status:  Explain what the next run will skip, from .ff-run/state.json
  - ff_inspect: Read-only SWD observation (reset cause / PC / variables / peripherals)
  - ff_monitor: Live serial panel (the only tool that starts one)

工具函数定义在模块级、由 MCP_TOOL_FUNCS 统一注册：schema 只从签名生成一份，
命令面的覆盖关系可以被测试直接断言（`tests/test_mcp_surface.py`）。

Usage (as MCP server):
    python -m firmforge.adapters.mcp_server
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

try:
    from mcp.server.fastmcp import FastMCP
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False

logger = logging.getLogger("firmforge.mcp")
logging.basicConfig(level=logging.INFO, stream=sys.stderr)

mcp = FastMCP("FirmForge", json_response=True) if MCP_AVAILABLE else None

def _add_project_root_to_path() -> Path:
    root = str(Path(__file__).resolve().parent.parent.parent)
    if root not in sys.path:
        sys.path.insert(0, root)
    return Path(root)


# -- Tool implementations --

def _do_detect(intent: str = "") -> dict[str, Any]:
    """Execute ff_detect."""
    try:
        root = _add_project_root_to_path()
        from firmforge.core.board_detector import BoardDetector
        detector = BoardDetector()
        result = detector.detect(user_text=intent)
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


def _do_context(board: str = "", topic: str = "") -> dict[str, Any]:
    """Execute ff_context — return board register/pin/baud reference.

    输出形状对所有板卡一致，字段取值一律走 ``core.board_view`` —— 板卡声明
    里 ``specs.flash`` / ``specs.clock`` 是字符串（``"2 MB"`` / ``"480 MHz"``），
    而这里要给的是字节数和赫兹。此前直接读 ``mcu.flash_size``（这个字段
    三块板卡都没有），导致 AVR 与 STM32 的 Flash 都显示 0。
    """
    try:
        _add_project_root_to_path()
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


def _stages_payload(result) -> list[dict[str, Any]]:
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
            info["serial_output"] = s.details.get("serial_output", "")[:200]
            if "pattern_match" in s.details:
                info["pattern_match"] = s.details["pattern_match"]
                info["expected"] = s.details.get("expected", "")
                info["actual"] = s.details.get("actual", "")[:200]
            if "panel_url" in s.details:
                info["panel_url"] = s.details["panel_url"]
                info["panel_file"] = s.details["panel_file"]
        out.append(info)
    return out


def _result_payload(result) -> dict[str, Any]:
    """一次流水线运行的通用结果帧。"""
    return {
        "overall_success": result.overall_success,
        "board": result.board,
        "total_elapsed_ms": round(result.total_elapsed_ms, 0),
        "stages": _stages_payload(result),
    }


def _do_build(board: str = "", app: str = "", workspace: str = "") -> dict[str, Any]:
    """Execute ff_build — Review + Build only."""
    _add_project_root_to_path()
    from firmforge.core.pipeline_runner import PipelineRunner
    from firmforge.infrastructure import paths

    runner = PipelineRunner(workspace=str(paths.resolve_workspace(workspace)))
    try:
        result = runner.build(source_dir=app or None, board_id=board or None)
    except Exception as e:
        return {"overall_success": False, "error": str(e), "stages": []}

    return _result_payload(result)


def _do_run(board: str = "", app: str = "", expected: str = "",
            workspace: str = "") -> dict[str, Any]:
    """Execute ff_run: Detect → Review → Build → Flash → Verify."""
    _add_project_root_to_path()
    from firmforge.core.pipeline_runner import PipelineRunner
    from firmforge.infrastructure import paths

    # 工作区必须是**调用方的工作区**，不是工具自己的安装目录。
    # 状态（.ff-run/state.json）、面板（serial_live.html）、串口配置
    # （serial_config.json）三者都要落在同一处，否则会出现「状态在这里、
    # 面板在那里」，串口参数还会被别的会话串改（实测误判过一次）。
    workspace = str(paths.resolve_workspace(workspace))
    logger.info("ff_run workspace = %s", workspace)
    runner = PipelineRunner(workspace=workspace)

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
        result = runner.run_full(
            source_dir=app or None,
            board_id=board or None,
            expected=expected or "",
            progress_callback=_on_progress,
            # MCP 调用没有「人在面板前」这回事。默认值本来就是「全关」
            # （panel_open="none" + panel_wait=0），这里显式写出来，是为了让
            # 「MCP 永远不碰面板」成为读得到的事实，而不是要靠猜默认值。
            # 面板文件仍在 stage.details 里（panel_url / panel_file），
            # 需要实时看的人自己调用 start_monitor 或打开那个文件。
            panel_open="none",
            panel_wait=0,
        )
    except Exception as e:
        return {"overall_success": False, "error": str(e), "stages": [],
                "progress": progress_events}

    payload = _result_payload(result)
    payload["progress"] = progress_events

    # 完整串口输出单独给一份（stage 里的 serial_output 截到 200 字），
    # Agent 要按行分析就得拿全文。
    serial_full = ""
    for s in result.stages:
        if s.name == "Verify":
            serial_full = s.details.get("serial_output", "")
            if "panel_url" in s.details:
                payload["panel_url"] = s.details["panel_url"]
                payload["panel_file"] = s.details["panel_file"]
            break
    payload["serial_lines"] = serial_full.splitlines() if serial_full.strip() else []
    return payload


def _do_flash(board: str = "", firmware: str = "", workspace: str = "",
              build: str = "") -> dict[str, Any]:
    """Execute ff_flash — 走 run_full(only=("flash",))，与 `ff flash` 同一入口。

    以前这里调 `PipelineRunner.flash()`，那条路**不读写 `.ff-run/state.json`**：
    MCP 烧完之后 `ff run` 仍认为没烧过，会再烧一遍，而两次之间没人被告知。
    CLI 侧修过一次，MCP 侧当时漏了 —— 所以现在两边都走 run_full。
    """
    _add_project_root_to_path()
    from firmforge.core.pipeline_runner import PipelineRunner
    from firmforge.infrastructure import paths

    try:
        runner = PipelineRunner(workspace=str(paths.resolve_workspace(workspace)))
        result = runner.run_full(board_id=board or None, only=("flash",),
                                 firmware=firmware or "", app_name=build or "")
    except Exception as e:
        return {"success": False, "error": str(e), "firmware": firmware}

    s4 = next((s for s in result.stages if s.name == "Flash"), None)
    return {
        "success": bool(result.overall_success),
        "board": result.board,
        "firmware": (s4.details.get("firmware_path", "") if s4 else ""),
        "bytes_written": (s4.details.get("bytes_written", 0) if s4 else 0),
        "elapsed_ms": round(result.total_elapsed_ms),
        "error": (s4.error if s4 and not s4.success else ""),
        "candidates": (s4.details.get("candidates", []) if s4 else []),
        "stages": _stages_payload(result),
    }


def _do_review(board: str = "", app: str = "", workspace: str = "") -> dict[str, Any]:
    """Execute ff_review — 只跑 S2（静态分析 + 寄存器审查 + 置信度）。"""
    _add_project_root_to_path()
    from firmforge.core.pipeline_runner import PipelineRunner
    from firmforge.infrastructure import paths

    if not app:
        return {"overall_success": False, "error": "app is required", "stages": []}

    runner = PipelineRunner(workspace=str(paths.resolve_workspace(workspace)))
    try:
        result = runner.run_full(source_dir=app, board_id=board or None,
                                 only=("review",))
    except Exception as e:
        return {"overall_success": False, "error": str(e), "stages": []}
    return _result_payload(result)


def _do_verify(board: str = "", expected: str = "",
               workspace: str = "") -> dict[str, Any]:
    """Execute ff_verify — 只跑 S5（开串口采样本 / 检查断言）。

    MCP 调用不碰面板：没有人在屏幕前点 Stop，起了也不会有人看。
    """
    _add_project_root_to_path()
    from firmforge.core.pipeline_runner import PipelineRunner
    from firmforge.infrastructure import paths

    runner = PipelineRunner(workspace=str(paths.resolve_workspace(workspace)))
    try:
        result = runner.run_full(board_id=board or None, expected=expected or "",
                                 only=("verify",), panel_open="none", panel_wait=0)
    except Exception as e:
        return {"overall_success": False, "error": str(e), "stages": []}

    payload = _result_payload(result)
    s5 = next((s for s in result.stages if s.name == "Verify"), None)
    payload["verdict"] = (getattr(s5, "verdict", "") if s5 else "") or ""
    payload["serial_lines"] = (s5.details.get("sample_lines", []) if s5 else [])
    return payload


def _do_status(workspace: str = "") -> dict[str, Any]:
    """Execute ff_status — 读 `.ff-run/state.json`，回答「下次会跳过什么、为什么」。"""
    _add_project_root_to_path()
    from firmforge.core.pipeline_state import PipelineState
    from firmforge.infrastructure import paths

    # 传了 workspace 就用它（CLI 总是传 "." 或 --workspace）；
    # 没传才去读 FIRMFORGE_WORKSPACE / cwd —— 与 _do_run 的解析规则一致，
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


def _do_inspect(board: str = "", build: str = "", elf: str = "", pc: int | None = None,
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
    _add_project_root_to_path()
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


# -- MCP tools --
#
# 工具函数定义在模块级、**不带装饰器**，最后统一注册。理由有三：
#   ① 没有装 mcp 库的环境（CI / 单测）也能 import 并反射签名 —— 否则「MCP 面
#      漏了哪条命令」只能靠人肉比对；
#   ② schema 只从签名生成一份，不再有手写的第二份（旧的 TOOL_SCHEMAS 全仓无人
#      引用，142 行死代码，其中 ff_context 的 topic 值域还是错的）；
#   ③ 函数名 = 工具名 = `ff_<子命令>`，与 CLI 一一对应，能被测试断言。

def _hex_addr(text: str) -> int:
    """地址按十六进制解析（与 CLI 的 --pc 同一规则）。

    不收十进制：`"800"` 在不同人脑子里分别是 800 和 0x800，地址没有十进制写法。
    """
    t = str(text).strip().replace("_", "")
    if t[:2].lower() == "0x":
        t = t[2:]
    return int(t, 16)


def ff_detect(intent: str = "") -> dict[str, Any]:
    """Scan USB ports to discover connected MCU development boards.

    Returns board ID, chip, and COM port. Call this FIRST to learn what hardware
    is actually attached.

    Args:
        intent: Optional short description of what the user wants to build. Used to
            disambiguate board candidates; omit if unsure.
    """
    return _do_detect(intent)


def ff_context(board: str = "", topic: str = "") -> dict[str, Any]:
    """Return board-specific registers, pin map, and baud rate presets.

    Call BEFORE writing MCU code. All register names MUST come from this reference
    to pass the hardware Source Review (register reference check).

    Args:
        board: Board ID (e.g. arduino_328p). Auto-detected if omitted.
        topic: "" or "all" (default) for the full reference; one of
            "registers" | "pins" | "baud"; or a concrete peripheral name
            ("USART1") / peripheral.register ("USART1.CR1") for an exact lookup.
            Names like "gpio"/"uart" are NOT topics — use the instance name.
    """
    return _do_context(board, topic)


def ff_build(board: str = "", app: str = "", workspace: str = "") -> dict[str, Any]:
    """Compile MCU source code only (no hardware required). Runs Review + Build.

    Use for CI/pre-commit checks. Use ff_run when hardware is connected.

    Args:
        board: Board ID. Auto-detected if omitted.
        app: Source code directory. REQUIRED.
        workspace: Project directory holding .ff-run/. Default: cwd.
    """
    return _do_build(board, app, workspace)


def ff_review(board: str = "", app: str = "", workspace: str = "") -> dict[str, Any]:
    """Run ONLY the static review stage (S2): cppcheck + register/field reference
    check + confidence scoring. Does not compile, flash, or touch hardware.

    Use when you changed code and want fast feedback on hallucinated register
    names / pin values without paying for a full build+flash cycle.

    Args:
        board: Board ID. Auto-detected if omitted.
        app: Source code directory. REQUIRED.
        workspace: Project directory holding .ff-run/. Default: cwd.
    """
    return _do_review(board, app, workspace)


def ff_run(board: str = "", app: str = "", expected: str = "",
           workspace: str = "") -> dict[str, Any]:
    """Compile, flash and run MCU code on real hardware.

    Full pipeline: Detect → Review → Build → Flash → Verify.
    Call AFTER writing code. Always returns when the pipeline finishes: no serial
    panel is opened and nothing waits for a human. The full serial capture is
    written to .ff-run/serial_live.html; call ff_monitor if a human wants live view.

    Args:
        board: Board ID. Auto-detected if omitted.
        app: Source code directory containing main.cpp/main.c. REQUIRED.
        expected: Optional regex that must match PERIODIC serial output
            (e.g. "HEARTBEAT tick=\\d+"). Do not assert on a one-shot boot banner —
            S5 opens the port only after flashing, so the banner is already gone.
        workspace: Project directory holding .ff-run/. Default: cwd.
    """
    return _do_run(board, app, expected, workspace)


def ff_flash(board: str, firmware: str = "", build: str = "",
             workspace: str = "") -> dict[str, Any]:
    """Flash a pre-compiled firmware to a board. Skips Review and Build.

    Shares the same .ff-run/state.json as ff_run, so a later ff_run will NOT
    re-flash needlessly.

    Args:
        board: Board ID. REQUIRED.
        firmware: Explicit path to firmware.hex. Takes priority over build.
        build: App name under the build cache (cache/build/<board>/<NAME>/).
            Required only when the cache holds several firmware images.
            NOTE: this is a build artifact name, NOT a source directory — for the
            source directory use ff_run/ff_build/ff_review's `app`.
        workspace: Project directory holding .ff-run/. Default: cwd.
    """
    return _do_flash(board=board, firmware=firmware, build=build,
                     workspace=workspace)


def ff_verify(board: str = "", expected: str = "", workspace: str = "") -> dict[str, Any]:
    """Run ONLY the serial verification stage (S5): open the port, collect samples,
    and check the assertion. Does not compile or flash.

    Use when the board already runs the firmware you want to check.

    Args:
        board: Board ID. Auto-detected if omitted.
        expected: Optional regex that must match periodic output. Without it the
            verdict is "collected" (data captured, no assertion) — NOT a pass.
        workspace: Project directory holding .ff-run/. Default: cwd.
    """
    return _do_verify(board, expected, workspace)


def ff_status(workspace: str = "") -> dict[str, Any]:
    """Explain what the next ff_run will skip and why, from .ff-run/state.json.

    Returns the four fingerprints (source / hex / port / board), each stage's status,
    the last error, and the skip rules. Use this when a run seems to have skipped
    a step you expected it to perform.

    Args:
        workspace: Project directory holding .ff-run/. Default: cwd.
    """
    return _do_status(workspace)


def ff_inspect(board: str = "", build: str = "", elf: str = "", pc: str = "",
               sym: list[str] | None = None, sym_glob: list[str] | None = None,
               periph: list[str] | None = None, no_where: bool = False,
               no_resume: bool = False, watchdog_run: bool = False,
               clear_reset_flags: bool = False, symbol_notes: str = "",
               timeout: float = 90.0) -> dict[str, Any]:
    """Read-only observation of a RUNNING STM32 target over SWD: reset cause, where
    the CPU is, live variable values, and decoded peripheral registers.

    STM32 only. Requires a debug probe. For a crash site, take the PC from the
    serial output and pass it as `pc` (offline mode, no probe needed).

    Args:
        board: Board ID. Defaults to the only STM32 board defined.
        build: App name under the build cache (cache/build/<board>/<NAME>/) whose ELF
            should be used for symbols. NOT a source directory.
        elf: Explicit ELF path. Alternative to `build`.
        pc: Program counter to resolve, hex string ("0x08001D78"). Offline: does not
            connect to the probe and cannot be combined with sym/sym_glob/periph.
        sym: Variable/array names to read (repeatable).
        sym_glob: Glob patterns for variables (repeatable), e.g. "g_rsv_*".
        periph: Peripherals to dump and decode (repeatable): "LPTIM1" for all
            registers, "LPTIM1.CR" for one.
        no_where: Do not resolve source line for the current PC.
        no_resume: Leave the target halted after observing (default: resume).
        watchdog_run: Let the watchdog keep running while halted (default: frozen —
            otherwise the target may reset mid-observation and the data breaks off).
        clear_reset_flags: Clear RCC_RSR reset flags after reading (otherwise the
            next read returns the same sticky bits).
        symbol_notes: YAML mapping symbol -> {value: meaning} to annotate values.
        timeout: OpenOCD session timeout in seconds (default 90).
    """
    pc_value = _hex_addr(pc) if str(pc).strip() else None
    return _do_inspect(board=board, build=build, elf=elf, pc=pc_value,
                       sym=sym, sym_glob=sym_glob, periph=periph,
                       no_where=no_where, no_resume=no_resume,
                       watchdog_run=watchdog_run,
                       clear_reset_flags=clear_reset_flags,
                       symbol_notes=symbol_notes, timeout=timeout)


def ff_monitor(port: str = "", baud: int = 9600, action: str = "start",
               workspace: str = "") -> dict[str, Any]:
    """Open/close the live serial panel — the ONLY MCP tool that starts a panel.

    ff_run never opens one, so use this when a human explicitly wants to watch
    the serial stream. Returns `panel_url` (use it as-is: the port may not be 9878
    if that one was taken) and `panel_file`.

    Args:
        port: COM port (e.g. "COM4"). Auto-detected when omitted.
        baud: Baud rate (default 9600).
        action: "start" to serve the panel, "stop" to close it.
        workspace: Project directory holding .ff-run/. Default: cwd.
    """
    return _do_monitor(port, baud, action, workspace=workspace)


#: 工具注册顺序 = 建议的调用顺序（先看硬件，再查参考，再改代码，再验证）。
MCP_TOOL_FUNCS = (
    ff_detect, ff_context, ff_build, ff_review,
    ff_run, ff_flash, ff_verify, ff_status, ff_inspect, ff_monitor,
)


if MCP_AVAILABLE and mcp is not None:
    for _tool in MCP_TOOL_FUNCS:
        mcp.tool()(_tool)

_monitor_httpd = None  # legacy — kept for backward compat with pipeline_runner


def _get_stream_queue():
    """Backward compat — delegates to panel_service."""
    from firmforge.adapters.panel_service import get_stream_queue
    return get_stream_queue()


def _clear_stream_queue():
    """Backward compat — delegates to panel_service."""
    from firmforge.adapters.panel_service import clear_stream_queue
    return clear_stream_queue()


def _start_monitor_httpd(root: str) -> int:
    """Backward compat — delegates to panel_service."""
    from firmforge.adapters.panel_service import start_panel_httpd
    return start_panel_httpd(root)


# -- Main entry point --

def _do_monitor(port: str = "", baud: int = 9600,
                action: str = "start", timeout: int = 0,
                workspace: str = "") -> dict[str, Any]:
    """Start/stop serial monitor + HTTP panel.

    start: auto-detect port, start collector + HTTP server, write goto_panel.html
    serve-only: start HTTP server only (collector already running from ff_run)
    stop: signal collector to exit + clean close port

    timeout: auto-stop after N seconds (0 = run indefinitely)
    """
    import subprocess
    import os
    import sys
    from pathlib import Path
    import time
    from firmforge.infrastructure import paths
    _add_project_root_to_path()
    # 面板服务的根 = 调用方工作区（与 ff_run 的 state.json 同一处）。
    root = paths.resolve_workspace(workspace)
    html_path = str(paths.runtime_dir(root) / "serial_live.html")
    goto_path = str(paths.runtime_dir(root) / "goto_panel.html")

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
        http_port = _start_monitor_httpd(str(root))

        # Write redirect page
        if http_port:
            try:
                with open(goto_path, "w", encoding="utf-8") as f:
                    f.write(f'<script>window.location.replace("http://127.0.0.1:{http_port}/serial_live.html");</script>')
            except Exception:
                pass

        return {
            "status": "started", "port": port, "baud": baud,
            "panel_url": f"http://127.0.0.1:{http_port}/serial_live.html" if http_port else "",
            "panel_file": f"{paths.RUNTIME_DIR_NAME}/goto_panel.html",
            "data_file": f"{paths.RUNTIME_DIR_NAME}/serial_live.html",
        }

    return {"status": "error", "message": f"unknown action: {action}"}


def main() -> None:
    """Run the MCP server over stdio."""
    if not MCP_AVAILABLE:
        print("ERROR: MCP Python SDK not installed.", file=sys.stderr)
        print("Install: pip install 'mcp>=1.2,<2'", file=sys.stderr)
        sys.exit(1)

    _add_project_root_to_path()
    global mcp
    if mcp is not None:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
