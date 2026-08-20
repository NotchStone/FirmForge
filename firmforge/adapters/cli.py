"""CLI adapter -- ff command entry point.

5-Stage Pipeline commands:
  ff detect       USB scan + board identification (5-Stage S1: Detect)
  ff detect       Scan USB for connected MCU boards (MCP: ff_detect)
  ff run <board> --app <dir>     Review → Build → Flash → Verify pipeline
  ff build <board> --app <dir>   Review + compile only
  ff flash <board> --firmware <hex>  Flash-only utility
  ff context [board] [--topic]   Chip knowledge reference (registers/pins/baud)
  ff setup                        Install toolchains

Machine-readable output: pass --json to any command (for agent/plugin integration).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from firmforge.core.board_detector import BoardDetector
from firmforge.core.resources import boards_dir as _bdir

logger = logging.getLogger(__name__)


def _json_out(obj: dict, exit_code: int = 0) -> int:
    """Print obj as JSON and return exit code (machine-readable output)."""
    print(json.dumps(obj, ensure_ascii=False, default=str, indent=2))
    return exit_code


def _detect_payload(detector: BoardDetector, result, args) -> dict:
    """Structured detect result (shared by json mode)."""
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
        "board_config": board_config,
    }


def cmd_detect(args: argparse.Namespace) -> int:
    """ff detect: USB scan + board identification."""
    detector = BoardDetector(boards_dir=args.boards_dir or Path(_bdir()))
    result = detector.detect(user_text=args.intent or "")

    if getattr(args, "json", False):
        return _json_out(_detect_payload(detector, result, args))

    print("FirmForge init: scanning for connected boards...")

    # Multiple boards detected — list all, let caller choose
    if not result.board_id and len(result.boards) > 1:
        print(f"\nDetected {len(result.boards)} board(s):")
        for i, c in enumerate(result.candidates, 1):
            port = c.details.get("port", "?")
            chip = c.details.get("chip", "?")
            print(f"  {i}. {c.board_id} — {chip} on {port} ({c.confidence:.0%})")
        print("\nTip: use --board to specify:")
        print("  ff verify <board_id> --app <source_dir>")
        print(f"\nAvailable board IDs: {', '.join(result.boards)}")
        return 0  # Detect succeeded — just report; caller decides

    if result.board_id:
        board_config = detector.resolve_board(result.board_id)
        if board_config:
            print(f"\nDetected board: {result.board_id}")
            print(f"  MCU: {board_config.get('mcu', {}).get('chip', 'unknown')}")
            print(f"  Clock: {board_config.get('specs', {}).get('clock', 'unknown')}")
            print(f"  Flash: {board_config.get('specs', {}).get('flash', 'unknown')}")
            if board_config.get("pins"):
                led = board_config["pins"].get("led_builtin", "N/A")
                print(f"  LED built-in: Pin {led}")
            print(f"\nDetection confidence: {result.candidates[0].confidence:.0%} "
                  f"(source: {result.candidates[0].source})")

            if args.intent:
                print(f"\nIntent: {args.intent}")
            return 0
        else:
            print(f"Warning: board {result.board_id} detected but board.json missing")
    else:
        print("\nNo board automatically identified "
              "(need >= 75% confidence for auto-detection).")

    # Show candidates even when below threshold — let user decide
    if result.candidates:
        print("\nDetected candidates (below auto-confirm threshold):")
        for i, c in enumerate(result.candidates, 1):
            port_info = c.details.get("port", "?")
            desc = c.details.get("description", "?")
            print(f"  {i}. {c.board_id} — {c.confidence:.0%} confidence "
                  f"(source: {c.source}, port: {port_info}, desc: {desc})")

        top = result.candidates[0]
        if len(result.candidates) == 1:
            print("\nTip: write code then run: ff verify --app <source_dir>")
        else:
            print("\nTip: write code then run: ff verify --app <source_dir>")

    # List available boards and ask user
    available = detector.list_available_boards(Path(args.boards_dir or str(_bdir())))
    if available:
        print("\nAvailable boards:")
        for b in available:
            print(f"  - {b}")
    else:
        print("\nNo board.json files found in boards/ directory.")

    print("\nPlease specify board manually: ff verify <board> --app <source_dir>")
    return 1


def _pipeline_payload(result) -> dict:
    """Serialize PipelineResult to a plain dict (json mode)."""
    return {
        "overall_success": result.overall_success,
        "board": result.board,
        "total_elapsed_ms": result.total_elapsed_ms,
        "stages": [
            {
                "stage": s.stage,
                "name": s.name,
                "success": s.success,
                "elapsed_ms": s.elapsed_ms,
                "details": s.details,
                "error": s.error,
            }
            for s in result.stages
        ],
    }


def cmd_run(args: argparse.Namespace) -> int:
    """ff run: Review → Build → Flash → Verify pipeline.

    Usage: ff run <board> --app <source_dir>
    """
    from firmforge.core.pipeline_runner import PipelineRunner


    workspace = Path(args.workspace or ".")
    board_id = args.board
    source_dir = args.app
    expected = getattr(args, "expected", "")

    if not source_dir:
        if getattr(args, "json", False):
            return _json_out({"error": "--app <source_dir> is required"}, 1)
        print("Error: --app <source_dir> is required")
        return 1

    runner = PipelineRunner(
        boards_dir=args.boards_dir or str(_bdir()),
        workspace=workspace,
    )

    result = runner.run_full(
        source_dir=source_dir,
        board_id=board_id or None,
        expected=expected,
    )

    if getattr(args, "json", False):
        return _json_out(_pipeline_payload(result), 0 if result.overall_success else 1)

    print("FirmForge 5-Stage Pipeline")
    if board_id:
        print(f"  Board: {board_id}")
    print(f"  Source: {source_dir}")
    print()

    for s in result.stages:
        icon = "PASS" if s.success else "FAIL"
        extra = ""
        if s.name == "Build" and s.details.get("compile_rounds", 0) > 1:
            extra = f" (attempt {s.details['compile_rounds']})"
        if s.details.get("skipped"):
            extra += " [skipped]"
        print(f"  [{icon}] Stage {s.stage} {s.name} ({s.elapsed_ms:.0f}ms){extra}")
        if s.error and not s.details.get("skipped"):
            print(f"         Error: {s.error[:150]}")

    if result.overall_success:
        print(f"  RESULT: ALL STAGES PASSED ({result.total_elapsed_ms:.0f}ms)")
        return 0
    else:
        failed = [s for s in result.stages if not s.success]
        print(f"  RESULT: {len(failed)} stage(s) failed ({result.total_elapsed_ms:.0f}ms)")
        for s in failed:
            detail = s.error or "unknown error"
            if s.name == "Build" and s.details.get("compile_rounds", 0) > 1:
                detail += f" (attempt {s.details['compile_rounds']})"
            print(f"    - Stage {s.stage} {s.name}: {detail}")
        return 1


def cmd_build(args: argparse.Namespace) -> int:
    """ff build: Review + Build only."""
    from firmforge.core.pipeline_runner import PipelineRunner


    workspace = Path(args.workspace or ".")
    source_dir = args.app
    if not source_dir:
        if getattr(args, "json", False):
            return _json_out({"error": "--app <source_dir> is required"}, 1)
        print("Error: --app <source_dir> is required")
        return 1

    runner = PipelineRunner(boards_dir=args.boards_dir or str(_bdir()), workspace=workspace)
    result = runner.build(source_dir=source_dir, board_id=args.board or None)

    if getattr(args, "json", False):
        return _json_out(_pipeline_payload(result), 0 if result.overall_success else 1)

    for s in result.stages:
        icon = "PASS" if s.success else "FAIL"
        extra = f" (attempt {s.details['compile_rounds']})" if s.name == "Build" and s.details.get("compile_rounds", 0) > 1 else ""
        print(f"  [{icon}] Stage {s.stage} {s.name} ({s.elapsed_ms:.0f}ms){extra}")

    if result.overall_success:
        print("  RESULT: BUILD PASSED")
        return 0
    else:
        for s in result.stages:
            if not s.success:
                print(f"  Error: {s.error or 'unknown'}")
        return 1


def cmd_flash(args: argparse.Namespace) -> int:
    """ff flash: flash-only utility."""
    board_id = args.board
    firmware = args.firmware

    if not board_id:
        if getattr(args, "json", False):
            return _json_out({"error": "board is required"}, 1)
        print("Usage: ff flash <board> --firmware <path>")
        return 1

    try:
        from firmforge.core.board_detector import BoardDetector
        from firmforge.providers.arduino.flash import ArduinoFlashProvider

        detector = BoardDetector(boards_dir=args.boards_dir or Path(_bdir()))
        config = detector.resolve_board(board_id)

        if not config:
            if getattr(args, "json", False):
                return _json_out({"error": f"board '{board_id}' not found"}, 1)
            print(f"Error: board '{board_id}' not found")
            return 1

        flasher = ArduinoFlashProvider(config)

        # Detect port
        port = flasher.detect_port()
        if not port:
            if getattr(args, "json", False):
                return _json_out({"error": "No COM port detected. Connect Arduino and retry."}, 1)
            print("Error: No COM port detected. Connect Arduino and retry.")
            return 1

        # Auto-detect firmware if not specified
        if not firmware:
            candidates = list(Path(".").rglob("firmware.hex"))
            if not candidates:
                if getattr(args, "json", False):
                    return _json_out({"error": "No firmware.hex found. Use --firmware <path>"}, 1)
                print("Error: No firmware.hex found. Use --firmware <path>")
                return 1
            firmware = str(candidates[0])
            print(f"Auto-detected firmware: {firmware}")

        if not getattr(args, "json", False):
            print(f"Port: {port}")

        result = flasher.flash(firmware)

        if getattr(args, "json", False):
            return _json_out({
                "success": result.success,
                "board": board_id,
                "port": port,
                "firmware": firmware,
                "bytes_written": result.bytes_written if hasattr(result, "bytes_written") else 0,
                "elapsed_ms": result.elapsed_ms if hasattr(result, "elapsed_ms") else 0,
                "error": result.stderr[-500:] if not result.success and hasattr(result, "stderr") else "",
            }, 0 if result.success else 1)

        if result.success:
            print(f"Flash SUCCESS ({result.bytes_written} bytes, {result.elapsed_ms:.0f}ms)")
            return 0
        else:
            print(f"Flash FAILED: {result.stderr[-200:]}")
            return 1

    except ImportError as e:
        if getattr(args, "json", False):
            return _json_out({"error": f"ArduinoFlashProvider not available: {e}"}, 1)
        print(f"ArduinoFlashProvider not available: {e}")
        return 1


def setup_argument_parser() -> argparse.ArgumentParser:
    """Build argument parser for ff CLI."""
    parser = argparse.ArgumentParser(
        prog="ff",
        description="FirmForge -- MCU Code Verification Toolchain",
    )
    parser.add_argument(
        "--version", action="version",
        version="FirmForge 0.2.0",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output machine-readable JSON (for agent/plugin integration)",
    )
    parser.add_argument(
        "--boards-dir", type=str, default=None,
        help="Override board definitions directory (default: bundled package data)",
    )
    parser.add_argument(
        "--workspace", "-w", type=str, default=".",
        help="Workspace directory for .firmforge/ artifacts",
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # ff detect
    p_init = subparsers.add_parser("detect", help="Scan USB and identify board")
    p_init.add_argument("intent", nargs="?", help="Optional: user intent description")

    # ff run
    p_run = subparsers.add_parser(
        "run", help="Execute hardware pipeline (Detect → Review → Build → Flash → Verify)",
    )
    p_run.add_argument("board", nargs="?", help="Board ID (e.g. arduino_328p)")
    p_run.add_argument("--app", help="Source code directory (REQUIRED)")
    p_run.add_argument("--expected", help="Regex pattern for expected serial output")

    # ff build
    p_build = subparsers.add_parser("build", help="Review and compile only (no flash/test)")
    p_build.add_argument("board", nargs="?", help="Board ID (e.g. arduino_328p)")
    p_build.add_argument("--app", help="Source code directory (REQUIRED)")

    # ff flash
    p_flash = subparsers.add_parser("flash", help="Flash firmware to board")
    p_flash.add_argument("board", nargs="?", help="Board ID")
    p_flash.add_argument("--firmware", "-f", help="Path to firmware.hex")

    # ff setup
    p_setup = subparsers.add_parser(
        "setup", help="Download & install toolchains (avr-gcc, avrdude) + Arduino Core",
    )

    # ff context
    p_ctx = subparsers.add_parser(
        "context", help="Query chip knowledge reference (registers/pins/baud) for a board",
    )
    p_ctx.add_argument("board", nargs="?", help="Board ID (auto-detect if omitted)")
    p_ctx.add_argument("--topic", default="",
                       help="Filter by topic (uart/spi/i2c/adc/timer/pwm/gpio)")

    return parser


def cmd_context(args: argparse.Namespace) -> int:
    """ff context: chip knowledge reference (registers/pins/baud)."""
    from firmforge.adapters.mcp_server import _do_context

    payload = _do_context(board=args.board or "", topic=args.topic or "")
    if getattr(args, "json", False):
        return _json_out(payload, 0 if "error" not in payload else 1)

    if "error" in payload:
        print(f"Error: {payload['error']}")
        return 1

    print(f"Board: {payload.get('board', '?')} | Chip: {payload.get('chip', '?')}")
    print(f"  Clock: {payload.get('clock_hz', '?')} Hz | Flash: {payload.get('flash_size', '?')}")
    regs = payload.get("registers", [])
    print(f"  Registers: {len(regs)} (topic filter: {args.topic or 'all'})")
    for r in regs[:10]:
        print(f"    - {r.get('name', '?')} @ {r.get('address', '?')} ({r.get('size', '?')}-bit)")
    if len(regs) > 10:
        print(f"    ... and {len(regs) - 10} more")
    pins = payload.get("pins", {})
    if pins:
        print(f"  Pins: {len(pins)}")
        for name, pin in list(pins.items())[:5]:
            print(f"    - {name}: {pin}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Main entry point for ff CLI."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s [%(name)s] %(message)s",
    )

    parser = setup_argument_parser()
    args = parser.parse_args(argv)

    if args.command == "detect":
        return cmd_detect(args)
    elif args.command == "run":
        return cmd_run(args)
    elif args.command == "build":
        return cmd_build(args)
    elif args.command == "flash":
        return cmd_flash(args)
    elif args.command == "setup":
        from firmforge.providers.arduino.setup import setup_all
        return setup_all()
    elif args.command == "context":
        return cmd_context(args)
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
