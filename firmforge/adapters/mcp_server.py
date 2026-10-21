"""MCP Server Adapter — FirmForge MCU code verification toolchain.

Exposes 5 MCP tools for AI Coding Agents:
  - ff_detect:  Scan connected MCU boards
  - ff_context: Return board-specific register/pin/baud reference
  - ff_run:    Review → Build → Flash → Verify (full hardware pipeline)

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

TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "ff_detect": {
        "name": "ff_detect",
        "description": (
            "Scan USB ports and identify connected MCU boards. "
            "Returns board ID, MCU chip, clock speed, flash size, "
            "and COM port. Call this to discover what hardware is available."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    "ff_context": {
        "name": "ff_context",
        "description": (
            "Return board-specific hardware reference: registers, pins, baud rates. "
            "Call this BEFORE writing MCU code to get valid register names "
            "and avoid hallucinated identifiers."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "board": {
                    "type": "string",
                    "description": "Board ID (e.g. arduino_328p). Auto-detected if omitted.",
                },
                "topic": {
                    "type": "string",
                    "description": "Optional: filter by peripheral (gpio, uart, spi, i2c, adc, timer, pwm)",
                },
            },
        },
    },
    "ff_build": {
        "name": "ff_build",
        "description": (
            "Compile MCU source code without flashing. "
            "Runs Source Review (register/pin reference check) → Build. "
            "Use to check if code compiles correctly."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "board": {"type": "string", "description": "Board ID. Auto-detected if omitted."},
                "app": {"type": "string", "description": "Path to source code directory. REQUIRED."},
            },
            "required": ["app"],
        },
    },
    "ff_run": {
        "name": "ff_run",
        "description": (
            "Verify, compile, flash and test MCU code on real hardware. "
            "Includes Source Review (register/pin reference check), confidence scoring, "
            "avr-gcc compilation, avrdude flashing, and serial output verification. "
            "Call this AFTER writing code to close the hardware loop."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "board": {
                    "type": "string",
                    "description": "Board ID (e.g. arduino_328p). Auto-detected if omitted.",
                },
                "app": {
                    "type": "string",
                    "description": "Path to source code directory containing main.cpp. REQUIRED.",
                },
                "expected": {
                    "type": "string",
                    "description": "Optional: regex pattern for expected serial output (e.g. 'HEARTBEAT')",
                },
            },
            "required": ["app"],
        },
    },
    "ff_flash": {
        "name": "ff_flash",
        "description": (
            "Flash a pre-compiled firmware.hex to a board. "
            "Use this to re-flash without recompiling."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "board": {
                    "type": "string",
                    "description": "Board ID (e.g. arduino_328p)",
                },
                "firmware": {
                    "type": "string",
                    "description": "Path to firmware.hex file",
                },
            },
            "required": ["board"],
        },
    },
    "ff_monitor": {
        "name": "ff_monitor",
        "description": (
            "Start/stop real-time serial output monitoring. "
            "Opens a browser panel automatically showing serial data from the MCU board. "
            "Use action='stop' to close the monitor."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "port": {
                    "type": "string",
                    "description": "COM port name (e.g. 'COM4'). Required for start.",
                },
                "baud": {
                    "type": "integer",
                    "description": "Baud rate (default 9600)",
                },
                "action": {
                    "type": "string",
                    "description": "'start' to begin monitoring, 'stop' to close",
                },
            },
        },
    },
}


def _add_project_root_to_path() -> Path:
    root = str(Path(__file__).resolve().parent.parent.parent)
    if root not in sys.path:
        sys.path.insert(0, root)
    return Path(root)


# -- Tool implementations --

def _do_detect() -> dict[str, Any]:
    """Execute ff_detect."""
    try:
        root = _add_project_root_to_path()
        from firmforge.core.board_detector import BoardDetector
        detector = BoardDetector()
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


def _do_build(board: str = "", app: str = "") -> dict[str, Any]:
    """Execute ff_build — Review + Build only."""
    root = _add_project_root_to_path()
    from firmforge.core.pipeline_runner import PipelineRunner

    runner = PipelineRunner(workspace=str(root))
    try:
        result = runner.build(source_dir=app or None, board_id=board or None)
    except Exception as e:
        return {"overall_success": False, "error": str(e), "stages": []}

    stages = []
    for s in result.stages:
        stage_info = {
            "stage": s.stage, "name": s.name, "success": s.success,
            "elapsed_ms": round(s.elapsed_ms, 0),
        }
        if s.error:
            stage_info["error"] = s.error[:200]
        if s.name == "Build" and s.details.get("compile_rounds", 0) > 0:
            stage_info["compile_rounds"] = s.details["compile_rounds"]
        if s.details.get("sub_stages"):
            stage_info["sub_stages"] = s.details["sub_stages"]
        stages.append(stage_info)

    return {
        "overall_success": result.overall_success,
        "board": result.board,
        "total_elapsed_ms": round(result.total_elapsed_ms, 0),
        "stages": stages,
    }


def _do_run(board: str = "", app: str = "", expected: str = "") -> dict[str, Any]:
    """Execute ff_run: Detect → Review → Build → Flash → Verify."""
    root = _add_project_root_to_path()
    from firmforge.core.pipeline_runner import PipelineRunner

    workspace = str(root)
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
        )
    except Exception as e:
        return {"overall_success": False, "error": str(e), "stages": [],
                "progress": progress_events}

    stages = []
    serial_full = ""
    for s in result.stages:
        stage_info = {
            "stage": s.stage,
            "name": s.name,
            "success": s.success,
            "elapsed_ms": round(s.elapsed_ms, 0),
        }
        if s.error:
            stage_info["error"] = s.error[:200]
        if s.details.get("sub_stages"):
            stage_info["sub_stages"] = s.details["sub_stages"]
        if s.name == "Review":
            stage_info["cppcheck"] = s.details.get("cppcheck", [])
            stage_info["warnings"] = s.details.get("warnings", [])
        if s.name == "Build" and s.details.get("compile_rounds", 0) > 0:
            stage_info["compile_rounds"] = s.details["compile_rounds"]
        if s.name == "Verify":
            # verdict 是 S5 的三态：verified / mismatch / collected / empty /
            # unavailable。只有 verified 才算「验证通过」；collected 表示
            # 「采到了数据但调用方没给断言」，需要 Agent 自己判断。
            stage_info["verdict"] = getattr(s, "verdict", "") or ""
            stage_info["sample_lines"] = s.details.get("sample_lines", [])
            stage_info["matched_baud"] = s.details.get("matched_baud", 0)
            serial_full = s.details.get("serial_output", "")
            stage_info["serial_output"] = serial_full[:200]
            if "pattern_match" in s.details:
                stage_info["pattern_match"] = s.details["pattern_match"]
                stage_info["expected"] = s.details.get("expected", "")
                stage_info["actual"] = s.details.get("actual", "")[:200]
            if "panel_url" in s.details:
                stage_info["panel_url"] = s.details["panel_url"]
                stage_info["panel_file"] = s.details["panel_file"]
        stages.append(stage_info)

    # Extract panel_url from Verify stage for convenience
    panel_info = {}
    for s in result.stages:
        if s.name == "Verify" and "panel_url" in s.details:
            panel_info["panel_url"] = s.details["panel_url"]
            panel_info["panel_file"] = s.details["panel_file"]
            break

    return {
        "overall_success": result.overall_success,
        "board": result.board,
        "total_elapsed_ms": round(result.total_elapsed_ms, 0),
        "stages": stages,
        "progress": progress_events,
        "serial_lines": serial_full.splitlines() if serial_full.strip() else [],
        **panel_info,
    }


def _do_flash(board: str = "", firmware: str = "") -> dict[str, Any]:
    """Execute ff_flash — flash pre-compiled hex via PipelineRunner."""
    root = _add_project_root_to_path()
    from firmforge.core.pipeline_runner import PipelineRunner

    try:
        runner = PipelineRunner(workspace=str(root))
        result = runner.flash(board_id=board or None, firmware_path=firmware)
        return {
            "success": result.overall_success,
            "board": result.board,
            "firmware": firmware,
            "stderr": next((s.error for s in result.stages if s.error), "")[:200],
            "stages": [
                {"stage": s.stage, "name": s.name, "success": s.success,
                 "elapsed_ms": round(s.elapsed_ms, 0)}
                for s in result.stages
            ],
        }
    except Exception as e:
        return {"success": False, "error": str(e), "firmware": firmware}


# -- MCP Tool registration --

if MCP_AVAILABLE and mcp is not None:

    @mcp.tool()
    def ff_detect() -> dict[str, Any]:
        """Scan USB ports to discover connected MCU development boards. Returns board ID, chip, and COM port."""
        _add_project_root_to_path()
        return _do_detect()

    @mcp.tool()
    def ff_context(board: str = "", topic: str = "") -> dict[str, Any]:
        """Return board-specific registers, pin map, and baud rate presets.
        Call BEFORE writing MCU code. All register names MUST come from this reference
        to pass the hardware Source Review (register reference check)."""
        _add_project_root_to_path()
        return _do_context(board, topic)

    @mcp.tool()
    def ff_build(board: str = "", app: str = "") -> dict[str, Any]:
        """Compile MCU source code only (no hardware required). Runs Review + Build. Use for CI/pre-commit checks. Use ff_run when hardware is connected."""
        _add_project_root_to_path()
        return _do_build(board, app)

    @mcp.tool()
    def ff_run(board: str = "", app: str = "", expected: str = "") -> dict[str, Any]:
        """Compile, flash and run MCU code on real hardware.
        Full pipeline: Detect → Review → Build → Flash → Verify.
        Call AFTER writing code. Returns sample serial lines for analysis + panel file for live monitor."""
        _add_project_root_to_path()
        return _do_run(board, app, expected)

    @mcp.tool()
    def ff_flash(board: str, firmware: str = "") -> dict[str, Any]:
        """Flash pre-compiled firmware.hex to a board. Bypasses Review+Build — use only with known-good hex files."""
        _add_project_root_to_path()
        return _do_flash(board, firmware)

    @mcp.tool()
    def ff_monitor(port: str = "", baud: int = 9600,
                   action: str = "start") -> dict[str, Any]:
        """Start/stop serial output monitoring in a browser panel.

        Args:
            port: COM port (e.g. 'COM4'). Required when action='start'.
            baud: Baud rate (default 9600).
            action: 'start' to open monitor, 'stop' to close it.

        Returns:
            dict with 'url' (http://localhost:9876) on start,
            or 'status': 'stopped' on stop.
            Agent should call present_files() with the URL to open the panel.
        """
        _add_project_root_to_path()
        return _do_monitor(port, baud, action)

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
                action: str = "start", timeout: int = 0) -> dict[str, Any]:
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
    root = _add_project_root_to_path()
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
