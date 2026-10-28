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

命令实现在 adapters/commands.py（与 CLI 共用同一份编排与 JSON 序列化），
本模块只保留 MCP 特有的东西：工具 schema（docstring）、注册、stdio transport。

工具函数定义在模块级、由 MCP_TOOL_FUNCS 统一注册：schema 只从签名生成一份，
命令面的覆盖关系可以被测试直接断言（`tests/test_mcp_surface.py`）。

Usage (as MCP server):
    python -m firmforge.adapters.mcp_server
"""

from __future__ import annotations

import logging
import sys
from typing import Any

try:
    from mcp.server.fastmcp import FastMCP
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False

from firmforge.adapters.commands import (
    _add_project_root_to_path,
    _hex_addr,
    do_build,
    do_context,
    do_detect,
    do_flash,
    do_inspect,
    do_monitor,
    do_review,
    do_run,
    do_status,
    do_verify,
)

logger = logging.getLogger("firmforge.mcp")
logging.basicConfig(level=logging.INFO, stream=sys.stderr)

mcp = FastMCP("FirmForge", json_response=True) if MCP_AVAILABLE else None


# -- MCP tools --
#
# 工具函数定义在模块级、**不带装饰器**，最后统一注册。理由有三：
#   ① 没有装 mcp 库的环境（CI / 单测）也能 import 并反射签名 —— 否则「MCP 面
#      漏了哪条命令」只能靠人肉比对；
#   ② schema 只从签名生成一份，不再有手写的第二份（旧的 TOOL_SCHEMAS 全仓无人
#      引用，142 行死代码，其中 ff_context 的 topic 值域还是错的）；
#   ③ 函数名 = 工具名 = `ff_<子命令>`，与 CLI 一一对应，能被测试断言。


def ff_detect(intent: str = "") -> dict[str, Any]:
    """Scan USB ports to discover connected MCU development boards.

    Returns board ID, chip, and COM port. Call this FIRST to learn what hardware
    is actually attached.

    Args:
        intent: Optional short description of what the user wants to build. Used to
            disambiguate board candidates; omit if unsure.
    """
    return do_detect(intent)


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
    return do_context(board, topic)


def ff_build(board: str = "", app: str = "", workspace: str = "") -> dict[str, Any]:
    """Compile MCU source code only (no hardware required). Runs Review + Build.

    Use for CI/pre-commit checks. Use ff_run when hardware is connected.

    Args:
        board: Board ID. Auto-detected if omitted.
        app: Source code directory. REQUIRED.
        workspace: Project directory holding .ff-run/. Default: cwd.
    """
    return do_build(board, app, workspace)


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
    return do_review(board, app, workspace)


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
    return do_run(board, app, expected, workspace)


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
    return do_flash(board=board, firmware=firmware, build=build,
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
    return do_verify(board, expected, workspace)


def ff_status(workspace: str = "") -> dict[str, Any]:
    """Explain what the next ff_run will skip and why, from .ff-run/state.json.

    Returns the four fingerprints (source / hex / port / board), each stage's status,
    the last error, and the skip rules. Use this when a run seems to have skipped
    a step you expected it to perform.

    Args:
        workspace: Project directory holding .ff-run/. Default: cwd.
    """
    return do_status(workspace)


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
    return do_inspect(board=board, build=build, elf=elf, pc=pc_value,
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
    return do_monitor(port, baud, action, workspace=workspace)


#: 工具注册顺序 = 建议的调用顺序（先看硬件，再查参考，再改代码，再验证）。
MCP_TOOL_FUNCS = (
    ff_detect, ff_context, ff_build, ff_review,
    ff_run, ff_flash, ff_verify, ff_status, ff_inspect, ff_monitor,
)


if MCP_AVAILABLE and mcp is not None:
    for _tool in MCP_TOOL_FUNCS:
        mcp.tool()(_tool)


# -- Main entry point --

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
