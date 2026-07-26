"""Cppcheck static analysis integration.

Invokes cppcheck as Phase 1 of S2 Review to catch logic bugs
(uninitialized variables, array overruns, dead code, etc.)
that compilers miss.

Output: list[dict] with {file, line, severity, message}
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Suppressions that match the target environment (AVR bare-metal)
_DEFAULT_SUPPRESS = [
    "missingIncludeSystem",     # avr/io.h not in cppcheck std libs
    "unusedFunction",           # ISR handlers appear unused
    "constParameter",           # common in callback-style code
]


def run_cppcheck(source_dir: str, *,
                 enable: str = "all",
                 verbose: bool = False) -> list[dict[str, Any]]:
    """Run cppcheck on a source directory, return structured warnings.

    Args:
        source_dir: Absolute path to directory containing .c/.cpp/.ino files.
        enable: Cppcheck checks to enable ("all", "warning", "style", etc.)
        verbose: Emit cppcheck stderr as warnings (for debugging).

    Returns:
        List of dicts: [{file, line, severity, message}, ...]
    """
    cppcheck_exe = _find_cppcheck()
    if not cppcheck_exe:
        raise FileNotFoundError(
            "Cppcheck not found. Install: winget install Cppcheck.Cppcheck")

    # Template format: machine-parseable
    template = "{file}:{line}:{severity}:{message}"

    cmd = [
        str(cppcheck_exe),
        "--enable=" + enable,
        "--template=" + template,
        "--inline-suppr",
        "--quiet",
    ]
    for s in _DEFAULT_SUPPRESS:
        cmd.append("--suppress=" + s)

    # Collect all .c/.cpp/.ino/.h files
    files: list[str] = []
    for ext in ("*.c", "*.cpp", "*.ino", "*.h"):
        for f in Path(source_dir).rglob(ext):
            if f.is_file():
                files.append(str(f))

    if not files:
        return []

    # Cppcheck is a native Windows binary; it needs Windows-style paths.
    # On MSYS2/Git Bash, Path() produces /c/... which cppcheck can't read.
    _files = _to_native_paths(files)

    cmd.extend(_files)

    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        logger.warning("Cppcheck timed out after 30s")
        return []
    except Exception as e:
        if verbose:
            logger.warning("Cppcheck invocation failed: %s", e)
        return []

    if verbose and r.stderr.strip():
        logger.warning("Cppcheck stderr: %s", r.stderr.strip())

    # Cppcheck outputs results to stderr (stdout is empty)
    output = r.stderr.strip()

    # Parse machine-parseable output, filter info-level noise
    warnings: list[dict[str, Any]] = []
    for line in output.split("\n"):
        line = line.strip()
        if not line:
            continue
        parts = line.split(":", 3)
        if len(parts) >= 4 and parts[2] != "information":
            try:
                warnings.append({
                    "file": parts[0],
                    "line": int(parts[1]) if parts[1].isdigit() else 0,
                    "severity": parts[2],
                    "message": parts[3],
                })
            except (ValueError, IndexError):
                warnings.append({
                    "file": parts[0] if len(parts) > 0 else "",
                    "line": 0,
                    "severity": "",
                    "message": line,
                })

    return warnings


def _find_cppcheck() -> Path | None:
    """Locate cppcheck.exe on PATH or in toolchain directory."""
    import shutil

    # 1. Check PATH first
    found = shutil.which("cppcheck")
    if found:
        return Path(found)

    # 2. Check FirmForge toolchain directory
    toolchain = Path.home() / ".firmforge" / "toolchains" / "cppcheck"
    exe = toolchain / "cppcheck.exe"
    if exe.exists():
        return exe

    # 3. Check default winget install path
    for loc in [
        Path.home() / "AppData" / "Local" / "Microsoft" / "WinGet" / "Packages",
        Path("C:/") / "Program Files" / "Cppcheck",
    ]:
        for f in loc.rglob("cppcheck.exe"):
            return f

    return None


def _to_native_paths(paths: list[str]) -> list[str]:
    """Convert paths for native Windows tool (MSYS2 /c/ → C:\\)."""
    import os as _os
    if _os.name != "nt":
        return paths

    result: list[str] = []
    for p in paths:
        # Git Bash style: /c/Users/... → use cygpath if available
        if p.startswith("/") and len(p) > 2 and p[2] == "/":
            try:
                import subprocess
                r = subprocess.run(
                    ["cygpath", "-w", p], capture_output=True, text=True, timeout=2)
                if r.returncode == 0 and r.stdout.strip():
                    result.append(r.stdout.strip())
                    continue
            except Exception:
                pass
        result.append(p)
    return result
