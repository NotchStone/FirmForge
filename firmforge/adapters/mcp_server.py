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
        detector = BoardDetector(boards_dir=str(root / "boards"))
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


def _do_context(board: str = "", topic: str = "") -> dict[str, Any]:
    """Execute ff_context — return board register/pin/baud reference."""
    try:
        root = _add_project_root_to_path()
        from firmforge.knowledge.knowledge_base import KnowledgeBase
        from firmforge.core.board_detector import BoardDetector

        if not board:
            detector = BoardDetector(boards_dir=str(root / "boards"))
            detect_result = detector.detect()
            board = detect_result.board_id or ""

        if not board:
            return {"error": "No board detected or specified. Run ff_detect first."}

        config = BoardDetector(boards_dir=str(root / "boards")).resolve_board(board) or {}
        mcu = config.get("mcu", {})
        chip = mcu.get("chip", "atmega328p").lower()

        knowledge_base = KnowledgeBase()
        knowledge_base.load_reference("avr", chip=chip)

        topic_filter = topic.lower() if topic else ""

        registers = knowledge_base.get_all_registers()
        if topic_filter:
            registers = {
                k: v for k, v in registers.items()
                if topic_filter in k.lower() or topic_filter in v.get("description", "").lower()
            }
        reg_list = list(registers.values())[:20] if not topic_filter else list(registers.values())

        pins = knowledge_base.get_pin_map(board) if board else {}

        return {
            "board": board,
            "chip": chip,
            "clock_hz": mcu.get("f_cpu", "16000000"),
            "flash_size": mcu.get("flash_size", 0),
            "features": config.get("features", {}),
            "registers": reg_list,
            "pins": pins,
            "topic": topic_filter or None,
        }
    except Exception as e:
        return {"error": str(e), "board": board or "unknown"}


def _do_build(board: str = "", app: str = "") -> dict[str, Any]:
    """Execute ff_build — Review + Build only."""
    root = _add_project_root_to_path()
    from firmforge.core.pipeline_runner import PipelineRunner

    runner = PipelineRunner(boards_dir=str(root / "boards"), workspace=str(root))
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
    runner = PipelineRunner(boards_dir=str(root / "boards"), workspace=workspace)

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
        runner = PipelineRunner(boards_dir=str(root / "boards"), workspace=str(root))
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
    root = _add_project_root_to_path()
    html_path = os.path.join(str(root), ".firmforge", "serial_live.html")
    goto_path = os.path.join(str(root), ".firmforge", "goto_panel.html")

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
                bd = BoardDetector(boards_dir=str(root / "boards"))
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
            "panel_file": ".firmforge/goto_panel.html",
            "data_file": ".firmforge/serial_live.html",
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
