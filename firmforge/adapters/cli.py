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
import time
import traceback
from pathlib import Path

from firmforge import __version__
from firmforge.core.board_detector import BoardDetector
from firmforge.core.resources import boards_dir as _bdir

logger = logging.getLogger(__name__)


def _json_out(obj: dict, exit_code: int = 0) -> int:
    """Print obj as JSON and return exit code (machine-readable output)."""
    print(json.dumps(obj, ensure_ascii=False, default=str, indent=2))
    return exit_code


_STAGE_TAG = {"Detect": "S1", "Review": "S2", "Build": "S3",
              "Flash": "S4", "Verify": "S5"}


class _Notes:
    """把流水线进度实时打到 stderr。

    为什么是 stderr，不是 stdout —— 两条都是实测出来的：

    ① `--json` 时 stdout 必须是**单个** JSON 对象，任何人类可读行都是污染。
    ② 用户常用 `ff run ... | Select-Object -Last 12`。PowerShell 会把
       **stdout** 缓冲到进程退出才一次性吐出，而 stderr 不经过那条管道，
       能逐行刷出来。之前整条流水线只在结束时打印汇总，于是 cppcheck 冷跑
       那 100 秒里屏幕上一个字都没有，看起来就是卡死（2026-10-27 实测）。
       只要写 stdout，这个现象就一点都不会改善。
    """

    def __init__(self) -> None:
        self._t0 = time.time()
        self._stage_t0 = self._t0

    def note(self, stage: str, message: str) -> None:
        """阶段**内部**的一行（cppcheck 启动、编译完成……）。"""
        tag = _STAGE_TAG.get(stage, stage)
        print(f"  [{tag} {time.time() - self._t0:6.1f}s] {message}",
              file=sys.stderr, flush=True)

    def stage_done(self, name: str, success: bool, details: dict,
                   error: str | None) -> None:
        """阶段结束的一行，兼作 `progress_callback`。

        与最终汇总表**故意重复**：滚动区留痕解决"当时发生了什么"，
        汇总表解决"整体结论是什么"。少任何一个都不行。
        """
        tag = _STAGE_TAG.get(name, name)
        skipped = bool((details or {}).get("skipped"))
        mark = "SKIP" if skipped else (" OK " if success else "FAIL")
        extra = ""
        if skipped:
            # 跳过的原因可能记在 `reason`（构建/烧录）或 `note`（S5 无串口）。
            # 少这个回退会打出 "SKIP Verify  None" —— 有回退才说得清为什么跳。
            why = (details or {}).get("reason") or (details or {}).get("note") or ""
            extra = f"  {why}" if why else ""
        elif not success and error:
            extra = f"  {error.splitlines()[0][:120]}"
        print(f"  [{tag} {time.time() - self._t0:6.1f}s] {mark} {name}{extra}",
              file=sys.stderr, flush=True)

    def header(self, board: str, source: str) -> None:
        print("FirmForge 5-stage pipeline", file=sys.stderr, flush=True)
        if board:
            print(f"  Board:  {board}", file=sys.stderr, flush=True)
        print(f"  Source: {source}", file=sys.stderr, flush=True)
        print("  （以下是实时进度；最终汇总会再打印一遍到标准输出）",
              file=sys.stderr, flush=True)


def cmd_detect(args: argparse.Namespace) -> int:
    """ff detect: USB scan + board identification."""
    detector = BoardDetector(boards_dir=args.boards_dir or Path(_bdir()))
    result = detector.detect(user_text=args.intent or "")

    if getattr(args, "json", False):
        from firmforge.adapters.commands import detect_payload
        return _json_out(detect_payload(detector, result))

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
            detail = result.candidates[0].details or {}
            if result.candidates[0].source == "swd_probe":
                # 说清这条结论的强度：DEV_ID 只能定到系列，"认出这块板"
                # 还依赖「注册表里只有一块声明了该 DEV_ID 的板卡」。
                print(f"  probe: {detail.get('probe') or '?'} | "
                      f"DEV_ID={detail.get('dev_id')} REV_ID={detail.get('rev_id')} "
                      f"({detail.get('elapsed_ms')} ms)")
                print("  注：DEV_ID 只能确定到系列（H742/743/753/750 同为 0x450），"
                      "板卡是按「唯一匹配的声明」推出来的")

            if args.intent:
                print(f"\nIntent: {args.intent}")
            return 0
        else:
            print(f"Warning: board {result.board_id} detected but board.json missing")
    else:
        print("\nNo board automatically identified "
              "(need >= 75% confidence for auto-detection).")
        for note in getattr(result, "notes", []) or []:
            print(f"  ! {note}")

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


def _stage_badge(stage) -> str:
    """阶段的显示标签。

    success 是二态，表达不了 S5 的「采到了数据但没人给断言」——
    那种情况既不是通过也不是失败，必须单独显示，否则就是把
    「我只采到了数据」说成「验证通过」。
    """
    verdict = getattr(stage, "verdict", "") or ""
    if verdict == "collected":
        return "COLLECT"
    if verdict == "unavailable":
        return "SKIP"
    return "PASS" if stage.success else "FAIL"


def _stage_extra(stage) -> str:
    """阶段行尾的补充说明（三态各自讲清楚发生了什么）。"""
    verdict = getattr(stage, "verdict", "") or ""
    if verdict == "collected":
        return " — collected only, no assertion (pass --expected to verify)"
    if verdict == "unavailable":
        note = stage.details.get("note") or "unavailable"
        return f" — {note}, readback not performed"
    if verdict == "port_busy":
        # 端口没打开 ≠ 固件没输出：失败在前提，固件根本没被检验。
        return " — serial port busy, firmware was never exercised"
    extra = ""
    if stage.name == "Build" and stage.details.get("compile_rounds", 0) > 1:
        extra = f" (attempt {stage.details['compile_rounds']})"
    if stage.details.get("skipped"):
        reason = stage.details.get("reason") or ""
        extra += f" [skipped{': ' + reason if reason else ''}]"
        # 跳过构建时说清「复用的是哪一份」—— 构建缓存跨项目共享，
        # 只写 [skipped] 的话，「烧的是不是最新固件」只能自己去 dir 查。
        fw = stage.details.get("firmware_path")
        if fw:
            if stage.details.get("firmware_exists") is False:
                extra += f" — !! 产物不存在：{fw}"
            else:
                size = stage.details.get("firmware_size")
                bits = [x for x in (
                    stage.details.get("firmware_mtime"),
                    f"{size} B" if size is not None else None,
                ) if x]
                extra += f" — 复用 {fw}" + (f"（{'，'.join(bits)}）" if bits else "")
    return extra


_PANEL_INFINITE = -1.0             # `--panel` 不带值：常驻，等人点 Stop


def _resolve_panel(args: argparse.Namespace) -> tuple[str, float | None]:
    """把 `--panel` 一个开关翻译成（开窗模式, 等待秒数）。

    **默认关闭**。这不是随手定的默认值，是产品定位：ff 的主要调用方是
    Agent / CI / MCP，它们没有「人坐在面板前点 Stop」这件事 —— 任何
    默认开启面板的路径，最终都会表现为「工具调用不返回」。2026-10-28 实测：
    五个阶段 44 秒跑完，然后挂在 `join()` 里 400 秒等一个不会来的 Stop。

    想看实时串口就显式要：
      - `--panel`     → 常驻，人点 Stop / 关窗结束
      - `--panel 120` → 留 120 秒后自动结束
      - 不写（默认）  → 不开窗、不等待、不打印地址、不打面板日志
    """
    want = getattr(args, "panel", None)
    if want is None:
        return "none", 0.0
    if want == _PANEL_INFINITE:
        return "auto", None
    if want <= 0:                  # `--panel 0` = 显式关掉，等价于不写
        return "none", 0.0
    return "auto", float(want)


def _note_panel(args: argparse.Namespace, mode: str, wait: float | None) -> None:
    """面板相关的话**只在显式要面板时说**。

    默认路径必须一个面板字都不打 —— 那是 Agent 的解析输出，多一行
    「面板未保留」就是每次调用都刷的噪声，还会让人以为哪一步出了问题。
    """
    if getattr(args, "json", False) or mode == "none":
        return
    if wait is None:
        print("  （S5 面板常驻：点 Stop / 关窗结束。这是显式 --panel 才有的行为）",
              file=sys.stderr, flush=True)


def _elapsed_desc(result) -> str:
    """耗时描述：流水线自身耗时，等面板的时间单独标注。

    两者混在一起时，一条 44 秒的流水线会显示成 444687 ms，而那个数字是
    「人什么时候点 Stop」，不是工具的性能指标 —— 放在同一个括号里就是在
    制造错误印象。
    """
    text = f"{result.total_elapsed_ms:.0f}ms"
    wait_ms = getattr(result, "panel_wait_ms", 0.0) or 0.0
    if wait_ms >= 500:
        text += f"，另有 {wait_ms / 1000:.1f}s 等面板（不计入流水线耗时）"
    return text


def cmd_run(args: argparse.Namespace) -> int:
    """ff run: Review → Build → Flash → Verify pipeline.

    Usage: ff run <board> --app <source_dir>
    """
    board_id = args.board
    source_dir = args.app
    expected = getattr(args, "expected", "")

    if not source_dir:
        if getattr(args, "json", False):
            return _json_out({"error": "--app <source_dir> is required"}, 1)
        print("Error: --app <source_dir> is required")
        return 1

    notes = _Notes()
    panel_open, panel_wait = _resolve_panel(args)
    if not getattr(args, "json", False):
        notes.header(board_id or "(自动识别)", source_dir)
        _note_panel(args, panel_open, panel_wait)

    from firmforge.adapters.commands import run_pipeline, result_payload
    result = run_pipeline(
        mode="run", board=board_id, app=source_dir, expected=expected,
        workspace=args.workspace or "", boards_dir=args.boards_dir,
        panel_open=panel_open, panel_wait=panel_wait,
        progress_callback=notes.stage_done, on_note=notes.note,
    )

    if getattr(args, "json", False):
        return _json_out(result_payload(result), 0 if result.overall_success else 1)

    print()
    print("FirmForge 5-Stage Pipeline")
    if board_id:
        print(f"  Board: {board_id}")
    print(f"  Source: {source_dir}")
    print()

    for s in result.stages:
        icon = _stage_badge(s)
        extra = _stage_extra(s)
        print(f"  [{icon}] Stage {s.stage} {s.name} ({s.elapsed_ms:.0f}ms){extra}")
        if s.error and not s.details.get("skipped"):
            print(f"         Error: {s.error[:150]}")
        note = s.details.get("note")
        if note and note not in extra:
            print(f"         Note: {note}")

    collected = [s for s in result.stages if getattr(s, "verdict", "") == "collected"]
    if result.overall_success:
        if collected:
            print(f"  RESULT: {len(result.stages)} stages done, S5 collected only "
                  f"(no assertion supplied) ({_elapsed_desc(result)})")
        else:
            print(f"  RESULT: ALL STAGES PASSED ({_elapsed_desc(result)})")
        return 0
    else:
        failed = [s for s in result.stages if not s.success]
        print(f"  RESULT: {len(failed)} stage(s) failed ({_elapsed_desc(result)})")
        for s in failed:
            detail = s.error or "unknown error"
            if s.name == "Build" and s.details.get("compile_rounds", 0) > 1:
                detail += f" (attempt {s.details['compile_rounds']})"
            print(f"    - Stage {s.stage} {s.name}: {detail}")
        return 1


def _parse_app_list(spec: str) -> list[str]:
    """解析 --apps 参数：逗号分隔，或 @file（每行一个目录）。

    只保留真实存在的目录，其余忽略但会打一条 warning —— 批量跑的时候
    一个打错的路径不该让整批停下来，但也绝不能不吭声。
    """
    items: list[str] = []
    raw = spec.strip()
    if raw.startswith("@"):
        path = Path(raw[1:])
        if not path.is_file():
            logger.warning("--apps 指向的文件不存在：%s", path)
            return []
        lines = path.read_text(encoding="utf-8").splitlines()
        items = [ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith("#")]
    else:
        items = [p.strip() for p in raw.split(",") if p.strip()]

    out: list[str] = []
    for it in items:
        if Path(it).is_dir():
            out.append(it)
        else:
            logger.warning("跳过不存在的目录：%s", it)
    return out


def _cmd_build_batch(args: argparse.Namespace, spec: str) -> int:
    """批量构建：一个进程连续跑多个 app 目录。

    存在的理由很具体：这台机器起一个 Python 进程要 ~1.9 s（实测，其中真正
    导入 firmforge 只占 0.25 s，其余是 Windows 进程创建），73 个用例光启动
    就是 2.3 分钟。批量模式把进程启动收成一次，**编译仍是一例一次**，
    不改变任何构建语义。
    """
    from firmforge.core.pipeline_runner import PipelineRunner

    targets = _parse_app_list(spec)
    if not targets:
        if getattr(args, "json", False):
            return _json_out({"error": "no valid app directory in --apps"}, 1)
        print("Error: --apps 里没有有效的目录")
        return 1

    workspace = Path(args.workspace or ".")
    boards_dir = args.boards_dir or str(_bdir())
    state_file = workspace / ".ff-run" / "state.json"
    quiet = bool(getattr(args, "json", False))

    t0 = time.time()
    results: list[dict] = []
    for src in targets:
        # 每个用例前清掉运行指纹。同一份 state.json 跨用例共享会串味：
        # 实测（2026-10-23）会出现「rc!=0 且 stdout/stderr 全空」的假失败。
        try:
            state_file.unlink()
        except OSError:
            pass

        # 每个用例用新的 runner，避免上一例残留的 detector / collector 引用
        runner = PipelineRunner(boards_dir=boards_dir, workspace=workspace)
        r = runner.build(source_dir=src, board_id=args.board or None)
        err = next((s.error for s in r.stages if not s.success), "")
        name = Path(src).name
        results.append({
            "app": src,
            "name": name,
            "pass": bool(r.overall_success),
            "elapsed_ms": round(r.total_elapsed_ms),
            "error": err,
        })
        if not quiet:
            print(f"  {'PASS' if r.overall_success else 'FAIL'} {name} "
                  f"({r.total_elapsed_ms:.0f}ms)")
            if not r.overall_success:
                print(f"        {err[:160] or 'unknown'}")

    passed = sum(1 for x in results if x["pass"])
    total_ms = (time.time() - t0) * 1000

    if quiet:
        return _json_out({"total": len(results), "passed": passed,
                          "failed": len(results) - passed,
                          "elapsed_ms": round(total_ms),
                          "results": results},
                         0 if passed == len(results) else 1)

    print(f"  BATCH: {passed}/{len(results)} build passed ({total_ms:.0f}ms)")
    return 0 if passed == len(results) else 1


def cmd_build(args: argparse.Namespace) -> int:
    """ff build: Review + Build only."""
    apps = getattr(args, "apps", "") or ""
    if apps:
        return _cmd_build_batch(args, apps)

    source_dir = args.app
    if not source_dir:
        if getattr(args, "json", False):
            return _json_out({"error": "--app <source_dir> is required"}, 1)
        print("Error: --app <source_dir> is required")
        return 1

    notes = _Notes()
    if not getattr(args, "json", False):
        notes.header(args.board or "(自动识别)", source_dir)

    from firmforge.adapters.commands import run_pipeline, result_payload
    result = run_pipeline(
        mode="build", board=args.board, app=source_dir,
        workspace=args.workspace or "", boards_dir=args.boards_dir,
        progress_callback=notes.stage_done, on_note=notes.note,
    )

    if getattr(args, "json", False):
        return _json_out(result_payload(result), 0 if result.overall_success else 1)

    print()
    for s in result.stages:
        icon = _stage_badge(s)
        extra = _stage_extra(s)
        print(f"  [{icon}] Stage {s.stage} {s.name} ({s.elapsed_ms:.0f}ms){extra}")

    if result.overall_success:
        print("  RESULT: BUILD PASSED")
        return 0
    else:
        for s in result.stages:
            if not s.success:
                print(f"  Error: {s.error or 'unknown'}")
        return 1


def cmd_review(args: argparse.Namespace) -> int:
    """ff review：只跑 S2（静态分析 + 寄存器审查 + 置信度）。

    存在的理由很具体：改完代码想确认"审查这关过不过"，不该被
    Build / Flash 拖进去；反过来改了知识库或豁免表想复验审查，也不该动板子。
    """
    source_dir = args.app
    if not source_dir:
        if getattr(args, "json", False):
            return _json_out({"error": "--app <source_dir> is required"}, 1)
        print("Error: --app <source_dir> is required")
        return 1

    notes = _Notes()
    if not getattr(args, "json", False):
        notes.header(args.board or "(自动识别)", source_dir)

    from firmforge.adapters.commands import run_pipeline, result_payload
    result = run_pipeline(
        mode="review", board=args.board, app=source_dir,
        workspace=args.workspace or "", boards_dir=args.boards_dir,
        progress_callback=notes.stage_done, on_note=notes.note,
    )

    if getattr(args, "json", False):
        return _json_out(result_payload(result), 0 if result.overall_success else 1)

    print()
    _print_stage_list(result)
    print(f"  RESULT: {'REVIEW PASSED' if result.overall_success else 'REVIEW FAILED'}"
          f" ({_elapsed_desc(result)})")
    return 0 if result.overall_success else 1


def cmd_verify(args: argparse.Namespace) -> int:
    """ff verify：只跑 S5（打开串口、采样本、匹配断言）。不编译、不烧录。

    板子上已经是想验的那份固件时用这个 —— 否则每次验串口都要重跑一遍
    cppcheck（冷跑约 100 秒）加编译，纯属浪费。
    """
    if not args.board:
        if getattr(args, "json", False):
            return _json_out({"error": "board is required"}, 1)
        print("Usage: ff verify <board> [--expected '<正则>']")
        return 1

    notes = _Notes()
    panel_open, panel_wait = _resolve_panel(args)
    if not getattr(args, "json", False):
        notes.header(args.board, "(不编译、不烧录，只验串口)")
        _note_panel(args, panel_open, panel_wait)

    from firmforge.adapters.commands import run_pipeline, result_payload
    result = run_pipeline(
        mode="verify", board=args.board,
        expected=getattr(args, "expected", "") or "",
        workspace=args.workspace or "", boards_dir=args.boards_dir,
        panel_open=panel_open, panel_wait=panel_wait,
        progress_callback=notes.stage_done, on_note=notes.note,
    )

    if getattr(args, "json", False):
        return _json_out(result_payload(result), 0 if result.overall_success else 1)

    print()
    _print_stage_list(result)
    s5 = next((s for s in result.stages if s.name == "Verify"), None)
    verdict = getattr(s5, "verdict", "") or ""
    print(f"  RESULT: verify {verdict or ('PASSED' if result.overall_success else 'FAILED')}"
          f" ({_elapsed_desc(result)})")
    return 0 if result.overall_success else 1


def cmd_flash(args: argparse.Namespace) -> int:
    """ff flash：只跑 S4（烧录）。不跑 Review、不跑 Build。

    两处修正（2026-10-27）：

    ① **走 PipelineRunner，与 ff run 共用 `.ff-run/state.json`**。旧实现自己
       new detector + provider，完全不碰 state —— 于是 `ff flash` 烧完之后
       `ff run` 仍认为「没烧过」，会再烧一遍，而两次之间没有任何人被告知。
    ② **hex 不再靠 `Path(".").rglob("firmware.hex")` 在当前目录瞎找**。
       构建缓存在 `cache/build/<板卡>/<项目>/` 下跨项目共享，在工作目录里
       rglob 既可能找不到，也可能找到**别的项目**的固件。现在按
       `--firmware` → state 记录 → 构建缓存（唯一才用，多份报错列候选）。
    """
    if not args.board:
        if getattr(args, "json", False):
            return _json_out({"error": "board is required"}, 1)
        print("Usage: ff flash <board> [--build <应用名>] [--firmware <path>]")
        return 1

    build = getattr(args, "build", None) or ""
    notes = _Notes()
    if not getattr(args, "json", False):
        notes.header(args.board, build or "(固件由 state/缓存解析)")

    from firmforge.adapters.commands import run_pipeline, flash_payload
    result = run_pipeline(
        mode="flash", board=args.board,
        firmware=args.firmware or "", app_name=build,
        workspace=args.workspace or "", boards_dir=args.boards_dir,
        progress_callback=notes.stage_done, on_note=notes.note,
    )

    s4 = next((s for s in result.stages if s.name == "Flash"), None)
    if getattr(args, "json", False):
        return _json_out(flash_payload(result), 0 if result.overall_success else 1)

    print()
    if s4 is None:
        print("  Error: 没有执行烧录阶段")
        return 1
    if s4.success:
        size = s4.details.get("bytes_written", 0)
        how = (f"{size} bytes" if isinstance(size, int) and size >= 0
               else "回读校验通过")
        print(f"  [PASS] Stage 4 Flash ({s4.elapsed_ms:.0f}ms)  {how}")
        return 0

    print(f"  [FAIL] Stage 4 Flash ({s4.elapsed_ms:.0f}ms)")
    print(f"         {s4.error or 'unknown'}")
    for c in s4.details.get("candidates", []):
        print(f"         --build {c['app']:18s} {c['size']} B  {c['mtime']}")
    return 1


def cmd_status(args: argparse.Namespace) -> int:
    """ff status：把 `.ff-run/state.json` 讲成人话。

    回答的是「为什么这次跳过了 / 为什么又重跑了」—— 这两个问题以前只能
    自己去读 state.json 并猜指纹语义。流水线的增量跳过是四指纹驱动的
    （源码 / hex / 端口 / 板卡），不提这个，跳过就会被当成 bug。
    """
    from firmforge.core.pipeline_state import PipelineState

    workspace = Path(args.workspace or ".")
    state = PipelineState(workspace)
    data = state.data

    if getattr(args, "json", False):
        from firmforge.adapters.commands import do_status
        return _json_out(do_status(workspace=str(workspace)))

    print(f"运行状态：{paths_runtime(workspace)}")
    if not data:
        print("  （空 —— 还没有跑过；下一次 ff run 会完整执行五个阶段）")
        return 0

    fps = data.get("fingerprints", {}) or {}
    print()
    print("四指纹（任一变化都会让对应阶段重跑）")
    for key, label in (("board_id", "板卡"), ("source", "源码"),
                       ("hex", "固件"), ("port", "端口")):
        val = fps.get(key, "")
        print(f"  {label:4s} {_short(val) if val else '(未记录)'}")

    print()
    print("阶段")
    for name in ("detect", "review", "build", "flash", "test"):
        entry = (data.get("stages", {}) or {}).get(name, {}) or {}
        status = entry.get("status", "pending")
        extra = ""
        if name == "build" and entry.get("hex"):
            extra = f"  {_artifact_desc(entry['hex'])}"
        if entry.get("error"):
            extra = f"  {str(entry['error']).splitlines()[0][:100]}"
        print(f"  {name:8s} {status}{extra}")

    last = data.get("last_error") or {}
    if last:
        # 阶段现在是 done 而 last_error 还在，是因为 mark_done 只清**该阶段**
        # 的 error 字段（mark_failed 另外往 last_error 里留了一份）。直接打
        # 「上次失败：build」会与上面的 build done 自相矛盾，所以要说清它是
        # 更早一次失败的记录。
        stage_now = state.stage_status(str(last.get("stage", "")))
        suffix = ("（该阶段现在已是 done —— 这条是更早一次失败的记录）"
                  if stage_now == "done" else "")
        print()
        print(f"上次失败：{last.get('stage', '?')} —— "
              f"{str(last.get('message', '')).splitlines()[0][:140]}{suffix}")

    ok = data.get("last_success") or {}
    if ok:
        print(f"最近成功：{ok.get('stage', '?')} @ {ok.get('at', '?')}")

    print()
    print("下次 ff run 的跳过条件（指纹一致才跳，任一变化就重跑）：")
    if not fps:
        print("  指纹为空 —— 五个阶段全部执行")
    else:
        # 不重算指纹（没有源码路径），所以只给条件，不假装预测结果。
        if state.stage_status("build") == "done" and fps.get("hex"):
            print("  S3 Build    源码 + 板卡指纹不变 → 跳过，复用上次 hex")
        if state.stage_status("flash") == "done":
            print("  S4 Flash    源码/固件/端口/板卡全不变 → 跳过；"
                  "给了 --expected 一律真烧")
        if state.stage_status("test") == "done":
            print("  S5 Verify   同上 → 跳过；给了 --expected 一律重验")
        if not any(state.stage_status(s) == "done"
                   for s in ("build", "flash", "test")):
            print("  没有可跳过的阶段 —— 会完整重跑")
    print()
    print("注意：S2 Review 不在跳过之列（cppcheck 自己的内容哈希缓存负责加速），"
          "源码一变它就是冷跑。只想烧录请用 ff flash。")
    return 0


def _short(text: str, n: int = 40) -> str:
    """指纹里存的是 SHA256 或长路径，全打出来没人看得下去。"""
    t = str(text)
    if len(t) <= n:
        return t
    if "/" in t or "\\" in t:                     # 路径：保留文件名 + 尾部
        return "…" + Path(t).name
    return t[:n] + "…"


def _artifact_desc(path: str) -> str:
    p = Path(path)
    try:
        st = p.stat()
        return (f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(st.st_mtime))}"
                f"，{st.st_size} B")
    except OSError:
        return "(文件不存在)"


def paths_runtime(workspace: Path) -> str:
    """`.ff-run/` 的绝对路径。相对路径在这里没有用 —— 读的人要能直接打开它。"""
    from firmforge.infrastructure import paths as _p
    return str(_p.runtime_dir(Path(workspace).resolve()))


def _print_stage_list(result) -> None:
    """阶段清单的通用渲染（build / review / flash / verify 共用）。"""
    for s in result.stages:
        icon = _stage_badge(s)
        extra = _stage_extra(s)
        print(f"  [{icon}] Stage {s.stage} {s.name} ({s.elapsed_ms:.0f}ms){extra}")
        if s.error and not s.details.get("skipped"):
            print(f"         Error: {s.error[:150]}")
        note = s.details.get("note")
        if note and note not in extra:
            print(f"         Note: {note}")


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
        "-v", "--verbose", action="store_true",
        help="显示 debug 级日志（逐文件审查结果、完整链接命令行等）。"
             "默认只留阶段进度与可操作告警 —— 逐文件的 INFO 会淹掉进度行",
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
    # 曾经是位置参数 `ff detect "点灯"` —— 与所有其他命令的 `<board>` 位置参数
    # 长得一样，于是 `ff detect gc_h743` 会被当成"用户意图文本"静默吞掉，
    # 不报错也不检测这块板。改成选项后，写错就是明确的 unrecognized arguments。
    p_init.add_argument("--intent", default="",
                        help="可选的用户意图描述（帮助消歧板卡候选）")

    # ff run
    p_run = subparsers.add_parser(
        "run", help="Execute hardware pipeline (Detect → Review → Build → Flash → Verify)",
    )
    p_run.add_argument("board", nargs="?", help="Board ID (e.g. arduino_328p)")
    p_run.add_argument("--app", help="Source code directory (REQUIRED)")
    p_run.add_argument(
        "--expected",
        help="断言（正则），必须能命中**周期性**输出，如 'HEARTBEAT tick=\\d+'。"
             "不要断言启动横幅：S5 在烧录完成后才打开串口，一次性打印早已发完。",
    )
    p_run.add_argument(
        "--panel", nargs="?", const=_PANEL_INFINITE, default=None, type=float,
        metavar="SEC",
        help="开启串口面板（**默认关闭**：不开窗、不等待、采完即返回）。"
             "不带值=常驻等人点 Stop；带秒数=留 SEC 秒后自动结束。"
             "只在需要人实时看波形时用，Agent / CI 调用不要加。",
    )

    # ff build
    p_build = subparsers.add_parser("build", help="Review and compile only (no flash/test)")
    p_build.add_argument("board", nargs="?", help="Board ID (e.g. arduino_328p)")
    p_build.add_argument("--app", help="Source code directory (REQUIRED, or use --apps)")
    p_build.add_argument("--apps",
                         help="Batch mode: comma-separated app dirs, or @file (one per line). "
                              "Runs all of them in ONE process — saves the per-example "
                              "Python startup (~1.9 s each on Windows).")

    # ff review
    p_review = subparsers.add_parser(
        "review", help="Stage 2 only: static analysis + register review + confidence",
    )
    p_review.add_argument("board", nargs="?", help="Board ID")
    p_review.add_argument("--app", help="Source code directory (REQUIRED)")

    # ff flash
    p_flash = subparsers.add_parser(
        "flash", help="Stage 4 only: flash a built firmware (does not review/build)",
    )
    p_flash.add_argument("board", nargs="?", help="Board ID")
    p_flash.add_argument("--firmware", "-f",
                         help="Path to firmware.hex（缺省按 state → 构建缓存解析）")
    p_flash.add_argument("--build", metavar="NAME", dest="build",
                         help="构建缓存里的应用名（cache/build/<board>/<NAME>/）。"
                              "缓存里有多份时必须指定")
    p_flash.add_argument("--app", metavar="NAME", dest="build",
                         action=_DeprecatedBuildArg, help=argparse.SUPPRESS)

    # ff verify
    p_verify = subparsers.add_parser(
        "verify", help="Stage 5 only: open the serial port and check the assertion "
                       "(does not build or flash)",
    )
    p_verify.add_argument("board", nargs="?", help="Board ID")
    p_verify.add_argument("--expected",
                          help="断言（正则），必须能命中**周期性**输出，如 'HB tick=\\d+'")
    p_verify.add_argument(
        "--panel", nargs="?", const=_PANEL_INFINITE, default=None, type=float,
        metavar="SEC",
        help="开启串口面板（默认关闭）。不带值=常驻等人点 Stop；带秒数=留 SEC 秒")

    # ff status
    p_status = subparsers.add_parser(
        "status", help="Show what the next ff run will skip and why (.ff-run/state.json)",
    )

    # ff setup
    p_setup = subparsers.add_parser(
        "setup", help="Download & install toolchains (avr-gcc, avrdude) + Arduino Core",
    )
    # 命令叫 setup 却只装 AVR 那一套（STM32 的 arm-none-eabi 与 OpenOCD 走各自的
    # 安装器）。不说清楚，STM32 用户会以为跑完 ff setup 就齐了，然后 S3 报"找不到编译器"。
    p_setup.add_argument(
        "platform", nargs="?", default="avr", metavar="PLATFORM",
        help="要安装的平台：avr（默认）。stm32 暂不代装，见 docs/STM32-工具链选型.md")

    # ff context
    p_ctx = subparsers.add_parser(
        "context", help="Query chip knowledge reference (registers/pins/baud) for a board",
    )
    p_ctx.add_argument("board", nargs="?", help="Board ID (auto-detect if omitted)")
    p_ctx.add_argument(
        "--topic", default="",
        help="省略=全部（all）。枚举：registers | pins | baud | all；"
             "也可给外设名（USART1）或 外设.寄存器（USART1.CR1）做精确查询。"
             "注意 gpio/uart/spi 这类名字**不是**有效主题（它们是外设名的一部分，"
             "请直接用 USART1 这样的实例名）")

    # ff inspect
    p_ins = subparsers.add_parser(
        "inspect",
        help="Read-only observation: reset cause / PC location / symbols / peripherals "
             "(STM32, via SWD probe)",
    )
    p_ins.add_argument("board", nargs="?",
                       help="Board ID（缺省=唯一一台 STM32 板卡）")
    p_ins.add_argument("--build", metavar="NAME", dest="build",
                       help="构建缓存里的应用名（cache/build/<board>/<NAME>/ 下的 ELF）。"
                            "与 --elf 二选一")
    p_ins.add_argument("--app", metavar="NAME", dest="build",
                       action=_DeprecatedBuildArg, help=argparse.SUPPRESS)
    p_ins.add_argument("--elf", help="ELF 路径（缺省=构建缓存里唯一的 firmware.elf；"
                                     "有多份时**必须**指定 --build 或 --elf）")
    p_ins.add_argument("--pc", metavar="0xADDR", type=_parse_pc,
                       help="只解析这个 PC 的源码位置，**不连探针**（离线）。"
                            "故障现场从串口拿到 pc 后用，如 --pc 0x08001D78")
    # --sym / --sym-glob / --periph 是全拼的简写。三个开关里两个用缩写、
    # 一个用全拼（--symbol-notes）会让人以为 --symbol 存在而 --periph 不存在。
    # 统一成全拼，缩写作别名保留（短写顺手，不必为了整齐禁用）。
    p_ins.add_argument("--symbol", "--sym", action="append", metavar="NAME",
                       dest="sym", help="读一个变量/数组（可重复），如 --symbol s_ticks")
    p_ins.add_argument("--symbol-glob", "--sym-glob", action="append",
                       metavar="PAT", dest="sym_glob",
                       help="按通配读一组变量（可重复），如 --symbol-glob 'g_rsv_*'")
    p_ins.add_argument("--peripheral", "--periph", action="append", metavar="NAME",
                       dest="periph",
                       help="读外设寄存器并解码字段（可重复）：LPTIM1 读全部，"
                            "LPTIM1.CR 只读一个")
    p_ins.add_argument("--no-where", action="store_true",
                       help="不解析 PC 对应的源码行")
    p_ins.add_argument("--no-resume", action="store_true",
                       help="观测完保持暂停（默认恢复运行）")
    # 原名 `--no-freeze-watchdog` 是双重否定（"不" + "冻结"），读一遍要在脑子里
    # 转两个弯。改成肯定式：--watchdog-run = 让看门狗继续跑。旧名保留。
    p_ins.add_argument("--watchdog-run", dest="watchdog_run", action="store_true",
                       help="暂停期间让看门狗继续跑（默认冻结 —— 不冻结时暂停期间"
                            "可能被看门狗复位，观测数据会半途断掉）")
    p_ins.add_argument("--no-freeze-watchdog", dest="watchdog_run",
                       action="store_true", help=argparse.SUPPRESS)
    p_ins.add_argument("--clear-reset-flags", action="store_true",
                       help="观测后清 RCC_RSR 复位标志（不清则下次读到的还是这批 sticky 位）")
    p_ins.add_argument("--symbol-notes", metavar="YAML",
                       help="符号语义表（符号名: {取值: 说明}），给变量值补一行人话")
    p_ins.add_argument("--timeout", type=float, default=90.0, metavar="SEC",
                       help="OpenOCD 会话超时（秒，默认 90）")

    # `--json` 原先只挂在根解析器上，于是只有 `ff --json run` 可用；
    # 写成 `ff run --json`（人/Agent 的第一直觉）会被 argparse 判为未知参数，
    # 而错误落在 stderr、stdout 一片空白 —— 看起来像"命令没输出"，极易误判。
    # 这里给每个子命令也挂一份（`SUPPRESS` 默认值，不覆盖根上的取值）。
    for _sp in (p_init, p_run, p_build, p_flash, p_review, p_verify, p_status,
                p_setup, p_ctx, p_ins):
        _sp.add_argument(
            "--json", action="store_true", default=argparse.SUPPRESS,
            help="输出机器可读 JSON（等价于全局 --json，可写在子命令之后）")
        # 同 --json：写在子命令之后也要认。`ff build x --app y -v` 是
        # 人的直觉写法，只挂在根上会被判未知参数（旧 --json 就踩过）。
        _sp.add_argument(
            "-v", "--verbose", action="store_true", default=argparse.SUPPRESS,
            help="显示 debug 级日志")

    return parser


def cmd_context(args: argparse.Namespace) -> int:
    """ff context: chip knowledge reference (registers/pins/baud)."""
    from firmforge.adapters.commands import do_context

    payload = do_context(board=args.board or "", topic=args.topic or "")
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


class _DeprecatedBuildArg(argparse.Action):
    """`ff flash --app` / `ff inspect --app` 的旧写法：值仍是「构建缓存应用名」。

    `--app` 在 `run` / `build` / `review` 里指的是**源码目录**，在这两条命令里
    指的是**构建缓存里的应用名**，同名两义正是最容易猜错的地方
    （`ff flash --app ./src` 会去找一个叫 `./src` 的缓存目录）。
    统一改名为 `--build`，旧写法继续可用但要说清它到底是什么。
    """

    def __call__(self, parser, namespace, values, option_string=None):  # noqa: ANN001
        print("提示：这里的 --app 指「构建缓存里的应用名」，已改名为 --build。"
              "（--app 在 run/build/review 里指源码目录，两者不是一回事）",
              file=sys.stderr, flush=True)
        setattr(namespace, self.dest, values)


def _parse_pc(text: str) -> int:
    """PC 一律按十六进制解析 —— 地址没有十进制写法。

    接受 `0x08001D78` / `08001D78` / `0x0800_1D78` 三种常见写法。
    不收十进制是为了避免 `--pc 800` 被读成 800 而不是 0x800。
    """
    t = text.strip().replace("_", "")
    if t[:2].lower() == "0x":
        t = t[2:]
    try:
        return int(t, 16)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"--pc 需要十六进制地址（如 0x08001D78），收到 {text!r}") from None


def cmd_inspect(args: argparse.Namespace) -> int:
    """ff inspect: 只读观测 —— 复位原因 / CPU 位置 / 关键变量 / 外设寄存器。

    参数校验与请求构造都在 `commands.do_inspect` 里 —— MCP 的 ff_inspect 调的是同一份，
    否则「CLI 允许 / MCP 拒绝」这种漂移迟早出现（board 自动选择、平台校验、
    pc 与读内存互斥这三段逻辑本来就有 30 行）。
    """
    from firmforge.adapters.commands import do_inspect

    payload = do_inspect(
        board=args.board or "",
        build=getattr(args, "build", None) or "",
        elf=getattr(args, "elf", None) or "",
        pc=getattr(args, "pc", None),
        sym=getattr(args, "sym", None),
        sym_glob=getattr(args, "sym_glob", None),
        periph=getattr(args, "periph", None),
        no_where=getattr(args, "no_where", False),
        no_resume=getattr(args, "no_resume", False),
        watchdog_run=getattr(args, "watchdog_run", False),
        clear_reset_flags=getattr(args, "clear_reset_flags", False),
        symbol_notes=getattr(args, "symbol_notes", None) or "",
        timeout=float(getattr(args, "timeout", None) or 90.0),
        boards_dir=args.boards_dir or str(_bdir()),
    )

    # 前提不成立（ELF 有歧义 / --elf 不存在）—— 报错退出，**不产出半份观测**。
    # 这类错误以前只落在 warnings 里，于是命令以 0 退回、还打印了一个
    # 属于另一个固件的 Where: 行。
    if payload.get("error"):
        if getattr(args, "json", False):
            return _json_out(payload, 2)
        print(f"Error: {payload['error']}")
        for line in payload.get("candidates") or []:
            print(f"  {line}" if line.startswith("  ") else f"  {line}")
        if payload.get("hint"):
            print(f"  {payload['hint']}")
        return 2

    if getattr(args, "json", False):
        return _json_out(payload, _inspect_exit_code(payload))

    _print_inspect(payload)
    return _inspect_exit_code(payload)


def _inspect_exit_code(payload: dict) -> int:
    """0 = 拿到了本次要的东西。

    离线 `--pc` 没有 halted 概念（压根没连板子），判据换成「源码行解出来了没」。
    """
    if payload.get("mode") == "offline":
        loc = payload.get("location") or {}
        return 0 if loc.get("line") or loc.get("function") else 1
    return 0 if (payload.get("target") or {}).get("halted") else 1


def _print_inspect(p: dict) -> None:
    """人读格式。要的是判据，不是 JSON 的换行版。"""
    t = p.get("target") or {}
    frozen = t.get("watchdog_frozen")
    offline = p.get("mode") == "offline"

    if offline:
        # 离线 --pc：没连探针。halted / reset / stack / 看门狗这些字段
        # **一个都不能打** —— 打出来就是让人以为连上板子了。
        print(f"Mode:  offline (--pc) — 未连接探针，只解析符号与源码行 | "
              f"{p.get('elapsed_ms')} ms")
        print(f"Board: {t.get('board_id')} | {t.get('mcu')}")
    else:
        state = "halted" if t.get("halted") else "NOT-HALTED"
        print(f"Board: {t.get('board_id')} | {t.get('mcu')} | {state} | "
              f"probe {t.get('probe') or '?'} | {p.get('elapsed_ms')} ms")
    if t.get("elf"):
        size = t.get("elf_size")
        size_txt = f", {size} B" if size else ""
        print(f"ELF:   {t['elf']}  ({t.get('elf_mtime') or '?'}{size_txt})")
    if t.get("state_prior"):
        print(f"  （进会话前状态：{t['state_prior']}）")

    rc = p.get("reset_cause")
    if rc:
        label = rc.get("primary") or ("已清除（无标志）" if rc.get("raw") == "0x00000000"
                                      else "无法判定")
        print(f"Reset: {label}  ({rc.get('raw')})")
        print(f"  {rc.get('note')}")
        if rc.get("flags"):
            print(f"  置位标志: {', '.join(rc['flags'])}")

    loc = p.get("location")
    if loc:
        where = ""
        if loc.get("file"):
            where = f"{_short_path(loc['file'])}:{loc.get('line') or '?'}"
        print(f"Where: {loc.get('pc')}  {loc.get('function') or '?'}  {where}".rstrip())

    if not offline:
        st = p.get("stack") or {}
        fault = st.get("fault")
        fault_txt = ("未判断" if fault is None
                     else (fault.get("exception") or "none") if fault.get("in_exception")
                     else "none")
        print(f"Stack: sp={st.get('sp')}  lr={st.get('lr')}  exception={fault_txt}")

    syms = p.get("symbols") or []
    if syms:
        print("Symbols:")
        for s in syms:
            val = s.get("value")
            val_txt = f"{val} (0x{val:08X})" if isinstance(val, int) else str(val)
            line = f"  {s['name']:<24} {s.get('addr')}  = {val_txt}"
            if s.get("text"):
                line += f"   → {s['text']}"
            print(line)
            words = s.get("words")
            if words:
                shown = " ".join(words[:8])
                more = f"  (+{len(words) - 8} 字)" if len(words) > 8 else ""
                print(f"  {'':<24} [{shown}]{more}")

    for per in p.get("peripherals") or []:
        print(f"Peripheral {per['name']} @ {per.get('base') or '?'}:")
        for r in per.get("registers") or []:
            if r.get("value") is None:
                print(f"  {r['name']:<8} (未读到)")
                continue
            fields = " ".join(f"{f['name']}={f['value']}" for f in r.get("fields") or [])
            print(f"  {r['name']:<8} {r['value']}  {fields}".rstrip())

    if frozen is not None:
        # 冻结状态必须显式可见：否则用户会把"暂停期间芯片复位"当成"没在跑"
        if not frozen:
            print("Watchdog: NOT frozen — 快照可能已被看门狗复位打断")
        elif t.get("watchdog_freeze_applied"):
            print("Watchdog: frozen（本次由 inspect 置位，退出时已恢复）")
        else:
            print("Watchdog: frozen（进入会话前就已置位，不是本次设置）")

    warns = p.get("warnings") or []
    if warns:
        print("Warnings:")
        for w in warns:
            print(f"  - {w}")


def _short_path(path: str) -> str:
    """厂商库的路径压成 `[vendor] 文件名` —— 目的是让人一眼看出
    「这行是我的代码还是库里的」，不是把 100 字符路径打在终端上。"""
    norm = path.replace("\\", "/")
    if "/packages/" in norm or "/src/templates/" in norm.lower():
        return "[vendor] " + norm.rsplit("/", 1)[-1]
    return path


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
    elif cmd == "inspect":
        ns.board = cargs.get("board")
        # `build` = 构建缓存里的应用名；旧键 `app` 兼容（当时与源码目录同名两义）。
        ns.build = cargs.get("build", cargs.get("app"))
        ns.elf = cargs.get("elf")
        ns.sym = cargs.get("sym") or []
        ns.sym_glob = cargs.get("sym_glob") or []
        ns.periph = cargs.get("periph") or []
        ns.no_where = bool(cargs.get("no_where", False))
        ns.no_resume = bool(cargs.get("no_resume", False))
        # 肯定式字段，旧键 no_freeze_watchdog 兼容。
        ns.watchdog_run = bool(cargs.get("watchdog_run",
                                         cargs.get("no_freeze_watchdog", False)))
        ns.clear_reset_flags = bool(cargs.get("clear_reset_flags", False))
        ns.symbol_notes = cargs.get("symbol_notes")
        ns.timeout = float(cargs.get("timeout") or 90.0)
    elif cmd == "run":
        ns.board = cargs.get("board")
        ns.app = cargs.get("app")
        ns.expected = cargs.get("expected", "")
        # 面板默认关闭：帧里没给 panel / panel_wait 就是「不开面板、不等」。
        # 调用方要留面板时传 {"panel": 120}（或 -1 = 常驻）。
        # 兼容旧字段 panel_wait / open_panel：open_panel="none" 一律视为关闭。
        _want = cargs.get("panel", cargs.get("panel_wait"))
        ns.panel = None if _want is None else float(_want)
        if cargs.get("open_panel") == "none":
            ns.panel = None
    elif cmd == "build":
        ns.board = cargs.get("board")
        ns.app = cargs.get("app")
    elif cmd == "flash":
        ns.board = cargs.get("board")
        ns.firmware = cargs.get("firmware")
        # `build` = 构建缓存里的应用名（与 CLI 的 --build 同名）。
        # 旧键 `app` 仍认：那时它和 run/build 的 --app（源码目录）同名两义。
        ns.build = cargs.get("build", cargs.get("app"))
    elif cmd == "review":
        ns.board = cargs.get("board")
        ns.app = cargs.get("app")
    elif cmd == "verify":
        ns.board = cargs.get("board")
        ns.expected = cargs.get("expected", "")
        _want = cargs.get("panel", cargs.get("panel_wait"))
        ns.panel = None if _want is None else float(_want)
        if cargs.get("open_panel") == "none":
            ns.panel = None
    elif cmd == "status":
        pass
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
        "review": cmd_review,
        "flash": cmd_flash,
        "verify": cmd_verify,
        "status": cmd_status,
        "inspect": cmd_inspect,
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
    """Main entry point for ff CLI.

    `--json` 调用方（Agent / 集成层）必须永远拿到一个 JSON 对象：
    旧实现在中途抛异常时**一行都不输出**，重定向得到 0 字节，
    调用方只能去 import 内部 API 才能取结果 —— 那等于把结构化接口废掉。
    现在任何未捕获异常都会落成一个 `{"error": ...}` 帧。
    """
    parser = setup_argument_parser()
    args = parser.parse_args(argv)

    # 日志级别要在 parse 之后才能定（-v 是命令行参数）。级别分界：
    #   INFO  = 阶段进度与需要人动手的告警
    #   DEBUG = 逐文件审查结果、完整链接命令行 —— 量太大，默认会淹掉进度行
    logging.basicConfig(
        level=logging.DEBUG if getattr(args, "verbose", False) else logging.INFO,
        format="%(levelname)s [%(name)s] %(message)s",
    )

    if args.json_mode:
        return _json_mode_loop()

    try:
        return _dispatch(args, parser)
    except SystemExit:
        raise
    except KeyboardInterrupt:
        raise
    except Exception as exc:                       # noqa: BLE001 — 顶层兜底
        logger.error("命令执行失败：%s", exc)
        logging.getLogger(__name__).debug("traceback", exc_info=True)
        if getattr(args, "json", False):
            return _json_out({
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(),
            }, 2)
        raise


def _dispatch(args, parser) -> int:
    """按子命令分发。抽出来是为了让 `main()` 有一处统一的异常出口。"""
    if args.command == "detect":
        return cmd_detect(args)
    elif args.command == "run":
        return cmd_run(args)
    elif args.command == "build":
        return cmd_build(args)
    elif args.command == "review":
        return cmd_review(args)
    elif args.command == "flash":
        return cmd_flash(args)
    elif args.command == "verify":
        return cmd_verify(args)
    elif args.command == "status":
        return cmd_status(args)
    elif args.command == "setup":
        platform = (getattr(args, "platform", "") or "avr").strip().lower()
        if platform != "avr":
            # 明确说"没装"，不要静默去装 AVR 那一套 —— 用户会以为 stm32 齐了。
            print(f"Error: ff setup 目前只代装 AVR 工具链（avr-gcc / avrdude / ArduinoCore-avr）。"
                  f"平台 '{platform}' 需手动安装：")
            print("  arm-none-eabi-gcc （14.2.Rel1）+ OpenOCD 0.12.0")
            print("  详见 docs/STM32-工具链选型.md；装好后用 ff inspect / ff flash 验证")
            return 1
        from firmforge.providers.arduino.setup import setup_all
        return setup_all()
    elif args.command == "context":
        return cmd_context(args)
    elif args.command == "inspect":
        return cmd_inspect(args)
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
