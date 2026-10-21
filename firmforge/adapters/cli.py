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

from firmforge import __version__
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
        panel_open=getattr(args, "open_panel", "auto"),
        panel_wait=getattr(args, "panel_wait", None),
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
        from firmforge.providers import get_flash_provider

        detector = BoardDetector(boards_dir=args.boards_dir or Path(_bdir()))
        config = detector.resolve_board(board_id)

        if not config:
            if getattr(args, "json", False):
                return _json_out({"error": f"board '{board_id}' not found"}, 1)
            print(f"Error: board '{board_id}' not found")
            return 1

        # 按平台路由，与 pipeline 同一入口：AVR 走 avrdude，STM32 走 OpenOCD + SWD。
        # 此前这里硬编码 ArduinoFlashProvider，STM32 板卡会撞在 avrdude 的 MCU_MAP 上，
        # 报出 "Unknown MCU chip 'STM32H743ZIT6'"，把「路由错了」伪装成「芯片不认识」。
        platform = config.get("platform", "arduino")
        flasher = get_flash_provider(platform, config)

        # 串口只服务「经串口烧录」的路线（avrdude）与 S5 回读。
        # SWD 路线不依赖串口，拿不到口只影响回读，不该阻断烧录。
        port = flasher.detect_port()
        if not port and platform == "arduino":
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
            if not getattr(args, "json", False):
                print(f"Auto-detected firmware: {firmware}")

        if not getattr(args, "json", False):
            print(f"Platform: {platform} | Port: {port or '(none — SWD 不依赖串口)'}")

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
            # bytes_written = -1 表示「写成功是回读校验确认的，字节数未知」，
            # 不能把 -1 直接打给人看。
            if getattr(result, "bytes_written", 0) >= 0:
                print(f"Flash SUCCESS ({result.bytes_written} bytes, {result.elapsed_ms:.0f}ms)")
            else:
                print(f"Flash SUCCESS (verified by read-back, {result.elapsed_ms:.0f}ms)")
            return 0
        else:
            print(f"Flash FAILED: {result.stderr[-200:]}")
            return 1

    except ImportError as e:
        if getattr(args, "json", False):
            return _json_out({"error": f"flash provider not available: {e}"}, 1)
        print(f"flash provider not available: {e}")
        return 1
    except Exception as e:
        # FlashError 是可预期失败（工具链缺件、OpenOCD 连不上、校验失败），
        # 给一行人话而不是 traceback；其余异常照旧抛出去。
        from firmforge.providers.base import ProviderError

        if not isinstance(e, ProviderError):
            raise
        if getattr(args, "json", False):
            return _json_out({"error": str(e)}, 1)
        print(f"Error: {e}")
        return 1


def setup_argument_parser() -> argparse.ArgumentParser:
    """Build argument parser for ff CLI."""
    parser = argparse.ArgumentParser(
        prog="ff",
        description="FirmForge -- MCU Code Verification Toolchain",
    )
    parser.add_argument(
        "--version", action="version",
        version=f"FirmForge {__version__}",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output machine-readable JSON (for agent/plugin integration)",
    )
    parser.add_argument(
        "--json-mode", action="store_true",
        help="Resident mode: read JSON command frames from stdin, emit result frames "
             "(for plugin/daemon integration; commands: detect/context/build/run/flash/exit)",
    )
    parser.add_argument(
        "--boards-dir", type=str, default=None,
        help="Override board definitions directory (default: bundled package data)",
    )
    parser.add_argument(
        "--workspace", "-w", type=str, default=".",
        help="Workspace directory for runtime artifacts (.ff-run/)",
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
    p_run.add_argument(
        "--open-panel", choices=["auto", "panel", "none"], default="auto",
        help="串口面板谁来开：auto=仅交互式终端自动打开（默认）/ panel=强制打开 / none=只打印地址",
    )
    p_run.add_argument(
        "--panel-wait", type=float, default=None, metavar="SEC",
        help="S5 采完样本后等面板多久（秒）。不写=无限等（人工点 Stop / 关窗）；0=立即结束（CI 用）",
    )

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
    p_ctx.add_argument(
        "--topic", default="",
        help="registers|pins|baud|all，或外设名（USART1）、外设.寄存器（USART1.CR1）")

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

    from firmforge.core.board_view import format_freq, format_size

    platform = payload.get("platform") or "?"
    series = payload.get("series")
    scope = f"{platform}/{series}" if series and series != platform else platform
    print(f"Board: {payload.get('board', '?')} | "
          f"Chip: {payload.get('chip') or '?'} ({scope})")
    print(f"  Clock: {format_freq(payload.get('clock_hz'))} | "
          f"Flash: {format_size(payload.get('flash_bytes'))} | "
          f"RAM: {format_size(payload.get('ram_bytes'))}")

    # 寄存器：分组统计 > 命中列表。两个分支的信息量不同，不能混着打。
    groups = payload.get("register_groups") or {}
    mode = payload.get("topic_mode", "all")
    if mode in ("all", "registers", "query"):
        if groups and mode in ("all", "registers"):
            total = payload.get("register_total", sum(groups.values()))
            print(f"  Registers: {total} across {len(groups)} peripherals"
                  f" — 用 --topic <外设名> 展开，如 --topic USART1")
            for name, count in sorted(groups.items())[:12]:
                print(f"    {name:<12} {count:>3} regs")
            if len(groups) > 12:
                print(f"    ... and {len(groups) - 12} more peripherals")
        else:
            regs = payload.get("registers", [])
            label = payload.get("topic") or "all"
            print(f"  Registers: {len(regs)} hit(s) (topic: {label})")
            for r in regs[:20]:
                where = f"{r['group']}.{r['name']}" if r.get("group") else r.get("name", "?")
                # None = 命中过多被省略；[] = 数据本身没有位域。两者不能都印 0。
                bits = r.get("fields")
                bits_txt = ("fields omitted" if bits is None
                            else f"{len(bits)} fields")
                print(f"    {where:<24} @ {str(r.get('address', '?')):<12} "
                      f"({r.get('size', '?')}-bit, {bits_txt})")
            if len(regs) > 20:
                print(f"    ... and {len(regs) - 20} more")
            if mode == "query" and not regs:
                print("    没有命中：换成外设名（USART1）或 外设.寄存器（USART1.CR1）再试")

    pins = payload.get("pins") or {}
    if pins.get("count"):
        fmt = pins.get("format")
        print(f"  Pins: {pins['count']} ({fmt})")
        for item in pins.get("items", [])[:8]:
            if fmt == "arduino":
                print(f"    D{item.get('arduino_pin', '?'):<3} "
                      f"P{item.get('port', '?')}{item.get('bit', '?')} "
                      f"({item.get('register', '?')}) "
                      f"{item.get('special') or ''}".rstrip())
            else:
                value = item.get("value")
                if isinstance(value, dict):
                    value = " ".join(f"{k}={v}" for k, v in value.items())
                print(f"    {str(item.get('name', '?')):<12} {value}")
        if pins["count"] > 8:
            print(f"    ... and {pins['count'] - 8} more pins")

    if payload.get("baud"):
        print("  Baud presets:")
        for baud, preset in list(payload["baud"].items())[:10]:
            print(f"    {baud:>7} -> UBRR {preset.get('ubrr')} "
                  f"({preset.get('ubrr_hex')}), err {preset.get('error_pct')}%")
    elif payload.get("baud_note"):
        print(f"  Baud: {payload['baud_note']}")

    origin = payload.get("origin") or {}
    reg_origin = origin.get("registers") if isinstance(origin, dict) else None
    if reg_origin:
        print(f"  Source: {reg_origin.get('zone')} 区 {reg_origin.get('path')}")
    return 0


def _emit_frame(req_id, ok, value, code=None, message=""):
    """Write one result frame (JSON line) to stdout — called outside redirect scope."""
    frame = {"id": req_id, "type": "result", "ok": bool(ok)}
    if value is not None:
        frame["value"] = value
    if code:
        frame["code"] = code
    if message:
        frame["message"] = message
    print(json.dumps(frame, ensure_ascii=False, default=str))


def _namespace(cmd: str, cargs: dict) -> argparse.Namespace:
    """Build an argparse.Namespace for a json-mode command (json forced on)."""
    ns = argparse.Namespace(
        command=cmd, json=True,
        boards_dir=cargs.get("boards_dir"),
        workspace=cargs.get("workspace") or ".",
    )
    if cmd == "detect":
        ns.intent = cargs.get("intent", "")
    elif cmd == "context":
        ns.board = cargs.get("board", "")
        ns.topic = cargs.get("topic", "")
    elif cmd == "run":
        ns.board = cargs.get("board")
        ns.app = cargs.get("app")
        ns.expected = cargs.get("expected", "")
    elif cmd == "build":
        ns.board = cargs.get("board")
        ns.app = cargs.get("app")
    elif cmd == "flash":
        ns.board = cargs.get("board")
        ns.firmware = cargs.get("firmware")
    return ns


def _json_mode_loop() -> int:
    """Resident loop: read JSON command frames from stdin, dispatch to cmd_*,
    wrap printed JSON output into result frames. Runs until an 'exit' frame."""
    import contextlib
    import io

    handlers = {
        "detect": cmd_detect,
        "context": cmd_context,
        "build": cmd_build,
        "run": cmd_run,
        "flash": cmd_flash,
    }

    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            _emit_frame(None, False, None, "PROTOCOL", "invalid JSON frame")
            continue
        req_id = req.get("id")
        cmd = req.get("cmd")
        cargs = req.get("args") or {}

        if cmd == "exit":
            return 0
        if cmd not in handlers:
            _emit_frame(req_id, False, None, "UNKNOWN_CMD",
                        f"unknown command '{cmd}'; supported: detect, context, build, run, flash, exit")
            continue

        args = _namespace(cmd, cargs)
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                rc = handlers[cmd](args)
        except Exception as exc:  # 基础设施失败 → error 帧，进程继续存活
            _emit_frame(req_id, False, None, "INTERNAL", f"{type(exc).__name__}: {exc}")
            continue

        out = buf.getvalue().strip()
        try:
            value = json.loads(out) if out else {}
        except json.JSONDecodeError:
            _emit_frame(req_id, False, None, "STDOUT",
                        f"non-JSON output from '{cmd}': {out[:200]}")
            continue
        _emit_frame(req_id, rc == 0, value)
    return 0


def main(argv: list[str] | None = None) -> int:
    """Main entry point for ff CLI."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s [%(name)s] %(message)s",
    )

    parser = setup_argument_parser()
    args = parser.parse_args(argv)

    if args.json_mode:
        return _json_mode_loop()

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
