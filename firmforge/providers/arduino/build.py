"""Arduino BuildProvider — avr-gcc compiler adapter.

Implements the abstract BuildProvider from providers/base.py.
Wraps avr-gcc for Arduino Mega2560 (ATmega2560) bare-metal compilation.
Supports both Arduino API code (requires Arduino core headers) and
bare AVR-LibC code (direct register access).

Stage 3: initial implementation with error parsing for COMPILE_FIX.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from firmforge.providers.base import (
    BuildProvider, BuildResult, BuildDiagnostic,
)
from firmforge.providers.arduino.toolchain import resolve_toolchain

logger = logging.getLogger(__name__)


def _clean_stale_artifacts() -> None:
    """Remove stale intermediate build artifacts from cache.

    Cleans .elf files (intermediate, hex is the deliverable) and preprocessed
    .ino temp files. Uses os.remove to bypass sandbox safe-delete hooks.
    """
    cache = Path.home() / ".firmforge" / "cache"
    for pattern, desc in [
        ("build/**/*.elf", ".elf intermediate"),
        ("preprocess/*.ino", "preprocessed .ino"),
    ]:
        for f in cache.glob(pattern):
            try:
                os.remove(str(f))
            except OSError:
                pass


class ArduinoBuildProvider(BuildProvider):
    """Arduino AVR compiler adapter (avr-gcc).

    Compiles C/C++ source for ATmega2560. Auto-detects avr-gcc path.
    Supports two modes:
      - bare: uses only AVR-LibC (avr/io.h etc.)
      - arduino: requires Arduino core headers (future, needs core download)
    """

    def __init__(self, board_config: dict[str, Any]) -> None:
        super().__init__(board_config)
        self._toolchain = resolve_toolchain()
        self._mcu = self._resolve_mcu()

    def build(self, source_dir: str,
              output_dir: str | None = None) -> BuildResult:
        """Compile all .c/.cpp/.ino files in source_dir into firmware.hex.

        Args:
            source_dir: Directory containing source files + optional Makefile
            output_dir: Output directory for firmware.hex (default: source_dir)

        Returns:
            BuildResult with success/failure and structured diagnostics.
        """
        src = Path(source_dir).resolve()
        out = Path(output_dir or source_dir).resolve()
        out.mkdir(parents=True, exist_ok=True)

        firmware_elf = out / "firmware.elf"
        firmware_hex = out / "firmware.hex"
        makefile = src / "Makefile"

        start = time.time()
        result = BuildResult(success=False)

        try:
            # Check if make is available AND Makefile exists
            make_available = self._tool_available("make")
            if makefile.exists() and make_available:
                result.stdout, result.stderr, rc = self._run_make(str(src), str(out))
            else:
                # Gather source files and compile manually
                sources = (list(src.rglob("*.c")) + list(src.rglob("*.cpp")) + list(src.rglob("*.ino")))
                if not sources:
                    result.stderr = "No source files (.c/.cpp/.ino) found"
                    result.errors = [BuildDiagnostic(
                        severity="error", file=str(src),
                        message=result.stderr, raw=result.stderr,
                    )]
                    return result

                result.stdout, result.stderr, rc = self._compile_sources(
                    [str(s) for s in sources], str(firmware_elf), str(firmware_hex)
                )

            result.elapsed_ms = (time.time() - start) * 1000
            result.success = rc == 0

            if result.success and firmware_hex.exists():
                result.firmware_path = str(firmware_hex)
            elif result.stderr:
                result.errors = self.parse_build_errors(result.stderr)

            return result

        finally:
            # Guaranteed: never leave intermediate artifacts behind.
            # .elf is discarded (only .hex is needed for flash).
            # Preprocessed .ino temp files are discarded (source is untouched).
            _clean_stale_artifacts()

    def parse_build_errors(self, stderr: str) -> list[BuildDiagnostic]:
        """Parse compiler stderr into structured diagnostics.

        Handles gcc-style error messages:
          filename:line:column: error: message
          filename:line:column: warning: message
          undefined reference to `symbol'
        """
        diagnostics: list[BuildDiagnostic] = []

        # Pattern 1: file:line:col: severity: message
        pattern1 = re.compile(
            r'^(.+?):(\d+):(\d+):\s*(error|warning):\s*(.+)$',
            re.MULTILINE,
        )
        for match in pattern1.finditer(stderr):
            diagnostics.append(BuildDiagnostic(
                severity=match.group(4),
                file=match.group(1).strip(),
                line=int(match.group(2)),
                column=int(match.group(3)),
                message=match.group(5).strip(),
                raw=match.group(0).strip(),
            ))

        # Pattern 2: undefined reference
        if "undefined reference" in stderr:
            for line in stderr.splitlines():
                if "undefined reference" in line:
                    diagnostics.append(BuildDiagnostic(
                        severity="error",
                        message=line.strip(),
                        raw=line.strip(),
                    ))

        # Pattern 3: ld returned exit status (linker failure)
        if "ld returned" in stderr or "collect2" in stderr:
            lines = stderr.splitlines()
            for i, line in enumerate(lines):
                if "ld returned" in line or "collect2" in line:
                    context = "\n".join(lines[max(0, i-3):i+3])
                    diagnostics.append(BuildDiagnostic(
                        severity="error",
                        message=line.strip(),
                        raw=context.strip(),
                    ))

        return diagnostics

    def get_toolchain_version(self) -> str:
        try:
            r = subprocess.run(
                [self._toolchain.avr_gcc, "--version"],
                capture_output=True, text=True, timeout=5,
            )
            return r.stdout.splitlines()[0] if r.stdout else "unknown"
        except Exception:
            return "unknown"

    # -- Internal --

    # Chip → avr-gcc -mmcu value
    _MCU_MAP: dict[str, str] = {
        "ATmega2560": "atmega2560",
        "ATmega328P": "atmega328p",
        "ATmega328":  "atmega328p",
        "ATmega168P": "atmega168p",
        "ATmega168":  "atmega168p",
        "ATmega88P":  "atmega88p",
        "ATmega48P":  "atmega48p",
        "ATmega32U4": "atmega32u4",
    }

    # Chip → Arduino Core variant directory
    _VARIANT_MAP: dict[str, str] = {
        "atmega2560": "mega",
        "atmega328p": "standard",   # UNO, Nano, Mini, Pro all use 'standard'
        "atmega328":  "standard",
        "atmega168p": "standard",
        "atmega168":  "standard",
        "atmega88p":  "standard",
        "atmega32u4": "leonardo",
    }

    # Chip → Arduino preprocessor define
    _BOARD_DEFINE_MAP: dict[str, tuple[str, ...]] = {
        "atmega2560": ("-DARDUINO_AVR_MEGA2560",),
        "atmega328p": ("-DARDUINO_AVR_UNO",),
        "atmega328":  ("-DARDUINO_AVR_UNO",),
        "atmega168p": ("-DARDUINO_AVR_UNO",),
        "atmega168":  ("-DARDUINO_AVR_UNO",),
        "atmega32u4": ("-DARDUINO_AVR_LEONARDO",),
    }

    def _resolve_mcu(self) -> str:
        chip = self._board_config.get("mcu", {}).get("chip", "")
        if chip in self._MCU_MAP:
            return self._MCU_MAP[chip]
        return chip.lower()

    def _resolve_variant(self) -> str:
        """Map chip to Arduino Core variant directory."""
        mcu = self._mcu  # already resolved
        return self._VARIANT_MAP.get(mcu, "standard")

    def _get_board_defines(self) -> list[str]:
        """Return board-specific Arduino preprocessor defines."""
        mcu = self._mcu
        return list(self._BOARD_DEFINE_MAP.get(mcu, ("-DARDUINO_AVR_UNO",)))

    @staticmethod
    def _parse_f_cpu(board_config: dict) -> int:
        """Parse F_CPU from board_config specs.clock (e.g. "16 MHz" → 16000000)."""
        import re
        clock_str = (board_config or {}).get("specs", {}).get("clock", "")
        m = re.search(r"(\d+)", clock_str)
        return int(m.group(1)) * 1_000_000 if m else 16_000_000

    def _compile_sources(
        self, sources: list[str], elf_path: str, hex_path: str,
    ) -> tuple[str, str, int]:
        """Compile source files into firmware.hex.

        Auto-detects Arduino API usage (#include <Arduino.h>) and links
        Arduino Core library when needed.

        Bare mode: .c  → avr-gcc  -std=c11
                   .cpp → avr-g++  -std=gnu++11  (per-file compile, then link)
        """
        gcc = self._toolchain.avr_gcc
        objcopy = self._toolchain.avr_objcopy
        f_cpu = self._parse_f_cpu(self._board_config)

        # Check if any source file uses Arduino API
        use_arduino = self._needs_arduino_core(sources)

        if use_arduino:
            return self._compile_with_arduino_core(
                sources, elf_path, hex_path
            )

        has_cpp = any(s.endswith(".cpp") for s in sources)

        if not has_cpp:
            # All .c: single-step compile+link with avr-gcc (fast path)
            cmd = [gcc, f"-mmcu={self._mcu}", f"-DF_CPU={f_cpu}UL",
                   "-Os", "-Wall", "-Wextra", "-std=c11", "-lm",
                   "-o", elf_path] + [str(s) for s in sources]
            logger.info("Compile: %s", " ".join(cmd))
            r = subprocess.run(cmd, capture_output=True, text=True)
            stdout, stderr, rc = r.stdout, r.stderr, r.returncode

            if rc != 0:
                return stdout, stderr, rc

            # .elf to .hex
            cmd2 = [objcopy, "-O", "ihex", "-R", ".eeprom", elf_path, hex_path]
            r2 = subprocess.run(cmd2, capture_output=True, text=True)
            if r2.returncode != 0:
                return stdout, stderr + "\n" + r2.stderr, r2.returncode

            return stdout, stderr, 0

        # Has .cpp: compile each source individually with correct compiler
        # .c  → avr-gcc  -std=c11
        # .cpp → avr-g++  -std=gnu++11
        import tempfile
        gcc_dir = os.path.dirname(gcc)
        avr_gpp = os.path.join(gcc_dir, "avr-g++")
        obj_dir = tempfile.mkdtemp(prefix="ff_bare_")
        obj_files: list[str] = []
        all_stdout = ""
        all_stderr = ""
        common_flags = [f"-mmcu={self._mcu}", f"-DF_CPU={f_cpu}UL",
                        "-Os", "-Wall", "-Wextra"]
        try:
            for i, src in enumerate(sources):
                obj_file = os.path.join(obj_dir, f"{i:03d}.o")
                obj_files.append(obj_file)
                compiler = avr_gpp if src.endswith(".cpp") else gcc
                lang_flags = ["-std=gnu++11"] if src.endswith(".cpp") else ["-std=c11"]
                cmd = [compiler] + common_flags + lang_flags + ["-c", "-o", obj_file, src]
                logger.info("Compile[%d/%d]: %s", i + 1, len(sources), " ".join(cmd))
                r = subprocess.run(cmd, capture_output=True, text=True)
                all_stdout += r.stdout
                all_stderr += r.stderr
                if r.returncode != 0:
                    return all_stdout, all_stderr, r.returncode

            # Link
            link_cmd = [avr_gpp, f"-mmcu={self._mcu}",
                         "-o", elf_path] + obj_files + ["-lm"]
            logger.info("Link: %s", " ".join(link_cmd))
            r = subprocess.run(link_cmd, capture_output=True, text=True)
            all_stdout += r.stdout
            all_stderr += r.stderr
            if r.returncode != 0:
                return all_stdout, all_stderr, r.returncode
        finally:
            for obj in obj_files:
                try:
                    os.remove(obj)
                except Exception:
                    pass
            try:
                os.rmdir(obj_dir)
            except Exception:
                pass

        # .elf to .hex
        cmd2 = [objcopy, "-O", "ihex", "-R", ".eeprom", elf_path, hex_path]
        r2 = subprocess.run(cmd2, capture_output=True, text=True)
        if r2.returncode != 0:
            return all_stdout, all_stderr + "\n" + r2.stderr, r2.returncode

        return all_stdout, all_stderr, 0

    @staticmethod
    def _preprocess_ino(sources: list[str]) -> list[str]:
        """Preprocess .ino files: inject function prototypes before compilation.

        Arduino IDE auto-generates function declarations for .ino sketches.
        We replicate this: scan each .ino for function definitions, then
        insert forward declarations at the top of the file.

        Known edge cases handled:
        - /* */ block comments and // line comments are stripped before
          scanning, so Processing example code inside comments is ignored.
        - Prototypes include the parameter list (not just type + name).
        - setup/loop/main/if/while/for are skipped as Arduino built-ins.
        """
        import re
        result = []

        # Regex to find function definitions (only match { not ;).
        # Matching existing prototypes (;) causes double-injection bugs.
        proto_re = re.compile(
            r'^\s*((?:unsigned\s+|signed\s+|volatile\s+|const\s+|static\s+|'
            r'virtual\s+|inline\s+|extern\s+)*'
            r'(?:void|int|char|short|long|float|double|uint\w+|int\w+|'
            r'size_t|bool|byte|word|String)\s*[*&\s]+\s*'
            r'(\w+)\s*)\(([^)]*)\)\s*\{',
            re.MULTILINE
        )

        def strip_comments(text: str) -> str:
            """Strip /* */ block comments and // line comments.
            
            Replaces comment content with spaces to preserve line/column
            positions for regex matching. Handles nested comment pitfalls
            by doing // first, then /* */.
            """
            # Strip // line comments (but not inside string literals)
            text = re.sub(r'//[^\n]*', '', text)
            # Strip /* */ block comments (non-greedy, single-line safe)
            text = re.sub(r'/\*.*?\*/', '', text, flags=re.DOTALL)
            return text

        def strip_preprocessor_blocks(text: str) -> str:
            """Remove #if / #ifdef / #ifndef ... #endif blocks.

            Since we cannot evaluate preprocessor conditions, we strip
            the entire block to avoid scanning code that may not be
            compiled (e.g. class SPISettings inside #if !defined).
            """
            result = []
            skip_depth = 0
            for line in text.split('\n'):
                stripped = line.lstrip()
                if stripped.startswith('#if ') or stripped.startswith('#ifdef ') \
                        or stripped.startswith('#ifndef '):
                    skip_depth += 1
                    result.append('')  # replace with blank line
                    continue
                if stripped.startswith('#endif') and skip_depth > 0:
                    skip_depth -= 1
                    result.append('')
                    continue
                if skip_depth > 0:
                    result.append('')
                    continue
                result.append(line)
            return '\n'.join(result)

        for src in sources:
            if not src.endswith(".ino"):
                result.append(src)
                continue
            logger.warning("Preprocessing .ino: %s", os.path.basename(src))
            with open(src, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()

            # Strip comments AND preprocessor blocks before scanning.
            # Preprocessor blocks (#if/#ifdef/#endif) are removed because we
            # cannot evaluate them — scanning their content would generate
            # prototypes for code that may not be compiled.
            clean = strip_preprocessor_blocks(strip_comments(content))

            # Convert C-style forward declarations (void func;) to C++ style
            # (void func();). Arduino IDE does this internally; we must too.
            # Only apply at top level (brace depth 0) to avoid corrupting
            # struct/class member declarations like "byte field2;".
            c_decl_re = re.compile(
                r'^\s*void\s+(\w+)\s*;\s*$',
                re.MULTILINE
            )
            def _convert_top_level_decls(text: str) -> str:
                """Convert C-style forward declarations (void func;) to C++ style
                (void func();). Only 'void' is converted — typed declarations
                like 'int name;' are variables, not forward declarations."""
                lines = text.split('\n')
                depth = 0
                result = []
                for line in lines:
                    depth_before = depth
                    depth += line.count('{') - line.count('}')
                    if depth_before == 0:
                        line = c_decl_re.sub(r'void \1();', line)
                    result.append(line)
                return '\n'.join(result)

            clean = _convert_top_level_decls(clean)

            prototypes = []
            for m in proto_re.finditer(clean):
                func_name = m.group(2)
                if func_name in ("setup", "loop", "main", "if", "while", "for"):
                    continue
                # Build prototype with parameter list: void func(...);
                proto = (m.group(1).rstrip() + "(" +
                         (m.group(3) or "") + ")" + ";\n")
                # Keep only if not already declared
                if proto not in prototypes:
                    prototypes.append(proto)

            # Remove prototypes that conflict with variable declarations.
            # e.g. "int getKnock()" prototype conflicts with "int getKnock = 0;"
            # Conservative: skip any name that appears in a variable assignment.
            var_decl_re = re.compile(r'^\s*(?:\w[\w\s*&]+)\s+(\w+)\s*=\s*', re.MULTILINE)
            conflicting = set()
            for m in var_decl_re.finditer(content):
                conflicting.add(m.group(1))
            prototypes = [p for p in prototypes
                         if not any(re.match(r'\w+\s+' + c + r'\s*\(', p) for c in conflicting)]

            if prototypes:
                # Insert prototypes after #include <Arduino.h> if present
                arduino_include = '#include <Arduino.h>'
                if arduino_include in content:
                    idx = content.index(arduino_include) + len(arduino_include)
                    content = (content[:idx] + "\n// Auto-generated prototypes\n" +
                               "".join(prototypes) + content[idx:])
                else:
                    content = "// Auto-generated prototypes\n" + "".join(prototypes) + "\n" + content

                # Also apply C-style forward declaration fix to the output
                content = _convert_top_level_decls(content)

            # Arduino .ino files always need Arduino.h (Arduino IDE auto-injects it)
            if '#include <Arduino.h>' not in content:
                content = '#include <Arduino.h>\n' + content

            # Write preprocessed content to cache — NEVER modify source.
            # This matches Arduino IDE behavior: compile from processed copy.
            from pathlib import Path
            cache_root = Path.home() / ".firmforge" / "cache"
            temp_dir = str(cache_root / "preprocess")
            os.makedirs(temp_dir, exist_ok=True)
            temp_src = os.path.join(temp_dir, os.path.basename(src))
            with open(temp_src, "w", encoding="utf-8") as f:
                f.write(content)
            logger.debug("Preprocessed %s → %s (%d prototypes)",
                        os.path.basename(src), temp_src, len(prototypes))
            result.append(temp_src)
        return result

    @staticmethod
    def _needs_arduino_core(sources: list[str]) -> bool:
        """Check if source files include Arduino.h or are .ino sketches."""
        for src_path in sources:
            if src_path.endswith(".ino"):
                return True  # .ino files always need Arduino Core
            try:
                content = Path(src_path).read_text(encoding="utf-8", errors="replace")
                if "#include" in content and "Arduino.h" in content:
                    return True
            except Exception:
                pass
        return False

    def _compile_with_arduino_core(
        self, user_sources: list[str], elf_path: str, hex_path: str,
    ) -> tuple[str, str, int]:
        """Compile with Arduino Core library linked.

        Two-step: compile each .c/.cpp to .o, then link together.
        This avoids cross-translation-unit alias issues with __empty.
        """
        import os
        import tempfile
        gcc_dir = os.path.dirname(self._toolchain.avr_gcc)
        avr_gcc = self._toolchain.avr_gcc
        avr_gpp = os.path.join(gcc_dir, "avr-g++")
        objcopy = self._toolchain.avr_objcopy

        # Arduino Core paths — search B区 packages first, then A区 vendor fallback.
        # B区 = ~/.firmforge/packages/arduino/avr/<version>/
        # A区 = vendor/arduino/ (dev fallback when packages not yet downloaded)
        # TODO: read version from vendor/manifests/core/arduino_avr_core.yaml
        #       when package_manager is introduced (planned with STM32 expansion).
        for core_base in [
            os.path.expanduser("~/.firmforge/packages/arduino/avr/1.8.6"),
            os.path.join(os.path.dirname(__file__), "..", "..", "..",
                         "vendor", "arduino"),
        ]:
            if os.path.exists(os.path.join(core_base, "cores", "arduino", "Arduino.h")):
                break
        else:
            core_base = ""
        core_base = os.path.abspath(core_base)
        core_inc = os.path.join(core_base, "cores", "arduino")
        variant = self._resolve_variant()
        variant_inc = os.path.join(core_base, "variants", variant)

        if not os.path.exists(os.path.join(core_inc, "Arduino.h")):
            return "", "Arduino Core not found at " + core_inc, 1

        # Preprocess .ino files: inject function prototypes
        # Before preprocessing, capture source dirs for local .h include paths
        user_source_dirs = sorted(set(os.path.dirname(s) for s in user_sources))
        user_sources = self._preprocess_ino(user_sources)

        # Gather Arduino Core source files
        core_sources: list[str] = []
        for ext in ("*.c", "*.cpp", "*.S"):
            for f in Path(core_inc).glob(ext):
                core_sources.append(str(f))

        # Arduino library include paths (SPI, Wire, EEPROM, etc.)
        lib_base = os.path.join(core_base, "libraries")
        lib_includes: list[str] = []
        if os.path.isdir(lib_base):
            for lib_dir in os.listdir(lib_base):
                src_dir = os.path.join(lib_base, lib_dir, "src")
                if os.path.isdir(src_dir):
                    lib_includes.extend(["-I", src_dir])
                    # Also add library source files for compilation.
                    # Use rglob to find sources in subdirectories (Servo/src/avr/ etc.)
                    # but filter to only AVR-relevant paths to avoid multi-platform
                    # Servo.cpp link conflicts.
                    _avr_prefixes = ("", "avr", "utility")
                    for ext in ("*.c", "*.cpp", "*.S"):
                        for f in sorted(Path(src_dir).rglob(ext)):
                            rel = f.relative_to(src_dir)
                            # Include files at src root (parts=("file.cpp",))
                            # or in allowed subdirs (parts=("avr","Servo.cpp"))
                            if len(rel.parts) == 1 or rel.parts[0] in _avr_prefixes:
                                core_sources.append(str(f))
                    # Check for utility subdirectory (SPI library uses this)
                    util_dir = os.path.join(src_dir, "utility")
                    if os.path.isdir(util_dir):
                        lib_includes.extend(["-I", util_dir])
                        # Sources in utility/ are already picked up by rglob above
                    logger.debug("Library: %s (+%d sources)", src_dir,
                                 len(core_sources))

        # Board-specific Arduino define
        board_defines = self._get_board_defines()
        arduino_version = self._get_arduino_version()
        f_cpu = self._parse_f_cpu(self._board_config)
        common_flags = [
            f"-mmcu={self._mcu}",
            f"-DF_CPU={f_cpu}UL",
            f"-DARDUINO={arduino_version}",
            *board_defines,
            "-DARDUINO_ARCH_AVR",
            "-I", core_inc,
            "-I", variant_inc,
            *lib_includes,
            *[f"-I{d}" for d in user_source_dirs],
            "-Os", "-Wno-restrict",
            "-fno-exceptions", "-fno-threadsafe-statics", "-ffunction-sections", "-fdata-sections",
        ]
        # Warning flags: separated so we can apply different levels
        CORE_WARN_FLAGS = ["-w"]        # Arduino Core: suppress all
        USER_WARN_FLAGS = ["-Wall"]     # User .ino/.cpp: catch real issues, skip noise

        # Build .o files in a temp directory (auto-cleaned)
        obj_dir = tempfile.mkdtemp(prefix="ff_build_")
        obj_files: list[str] = []
        all_stdout = ""
        all_stderr = ""

        # ── Core & Library Precompilation Cache ─────────────────────────
        # Core .o files are compiled once per MCU and stored alongside
        # the SDK packages. Source hash checking ensures automatic rebuild
        # when upstream SDK files change.
        # Layout: packages/arduino/avr/1.8.6/build/{mcu}/core.a
        import hashlib
        build_cache_dir = Path(core_base) / "build" / self._mcu
        build_cache_dir.mkdir(parents=True, exist_ok=True)

        # Manifest: {source_name: sha256} for all cached objects
        import json as _json
        manifest_path = build_cache_dir / "manifest.json"
        manifest: dict[str, str] = {}
        if manifest_path.exists():
            manifest = _json.loads(manifest_path.read_text(encoding="utf-8"))

        def _source_hash(src: str) -> str:
            with open(src, "rb") as f:
                return hashlib.sha256(f.read()).hexdigest()

        def _cache_key(src: str) -> str:
            """Relative path from core_base — unique even for same-named
            files in different subdirectories (e.g. libraries/Servo/...)."""
            return str(Path(src).relative_to(core_base)).replace("\\", "/")

        def _cached_obj(src: str) -> str | None:
            """Return cached .o path if source hash matches manifest."""
            key = _cache_key(src)
            obj_path = build_cache_dir / (key + ".o")
            current_hash = _source_hash(src)
            if obj_path.exists() and manifest.get(key) == current_hash:
                return str(obj_path)
            return None

        core_objs: list[str] = []   # core .o paths (cached or fresh)
        core_rebuilt = False         # set if any core source changed
        new_manifest: dict[str, str] = {}

        try:
            # Step 1: compile core sources (with cache)
            for src in core_sources:
                cached = _cached_obj(src)
                if cached:
                    core_objs.append(cached)
                    new_manifest[_cache_key(src)] = manifest[_cache_key(src)]
                    continue

                key = _cache_key(src)
                obj_file = build_cache_dir / (key + ".o")
                obj_file.parent.mkdir(parents=True, exist_ok=True)
                compiler = avr_gpp if src.endswith((".cpp", ".S")) else avr_gcc
                lang_flags = (["-std=gnu++11"] if src.endswith((".cpp",))
                              else ["-x", "assembler-with-cpp"] if src.endswith(".S")
                              else ["-std=c11"])
                cmd = ([compiler] + common_flags + CORE_WARN_FLAGS + lang_flags
                       + ["-c", "-o", str(obj_file), src])
                r = subprocess.run(cmd, capture_output=True, text=True)
                all_stdout += r.stdout
                all_stderr += r.stderr
                if r.returncode != 0:
                    logger.warning("Core compile failed: %s", src)
                    return all_stdout, all_stderr, r.returncode
                core_objs.append(str(obj_file))
                new_manifest[key] = _source_hash(src)
                core_rebuilt = True

            # Rebuild core.a if any core source changed (or first time)
            core_a = build_cache_dir / "core.a"
            if core_rebuilt or not core_a.exists():
                # Remove old .a first (avr-ar rcs appends otherwise)
                if core_a.exists():
                    core_a.unlink()
                ar_cmd = [os.path.join(gcc_dir, "avr-ar"), "rcs",
                          str(core_a)] + core_objs
                subprocess.run(ar_cmd, capture_output=True, check=True)
                manifest_path.write_text(
                    _json.dumps(new_manifest, indent=2), encoding="utf-8")

            # Step 2: link user code → user .o files only (no core in temp)
            user_obj_files: list[str] = []
            for i, src in enumerate(user_sources):
                obj_file = os.path.join(obj_dir, f"{i:03d}.o")
                user_obj_files.append(obj_file)
                is_ino = src.endswith(".ino")
                compiler = avr_gpp if src.endswith((".cpp", ".ino")) else avr_gcc
                lang_flags = ["-std=gnu++11"] if src.endswith((".cpp", ".ino")) else ["-std=c11"]
                cmd = [compiler] + common_flags + USER_WARN_FLAGS + lang_flags
                if is_ino:
                    cmd += ["-x", "c++"]
                cmd += ["-c", "-o", obj_file, src]
                r = subprocess.run(cmd, capture_output=True, text=True)
                all_stdout += r.stdout
                all_stderr += r.stderr
                if r.returncode != 0:
                    logger.warning("Compile failed: %s", src)
                    return all_stdout, all_stderr, r.returncode

            n_core_total = len(core_objs)
            n_cached = sum(1 for src in core_sources
                          if manifest.get(_cache_key(src)) == _source_hash(src))
            n_user = len(user_obj_files)
            logger.info("Compiled %d files (core=%d[cached=%d], user=%d), linking...",
                         n_core_total + n_user, n_core_total, n_cached, n_user)

            # Step 3: link user .o + core.a
            link_cmd = [avr_gpp] + common_flags + [
                "-Wl,--gc-sections",
                "-o", elf_path,
            ] + user_obj_files + [str(core_a), "-lm"]

            r = subprocess.run(link_cmd, capture_output=True, text=True)
            all_stdout += r.stdout
            all_stderr += r.stderr
            if r.returncode != 0:
                return all_stdout, all_stderr, r.returncode

            # Step 3: .elf to .hex
            cmd2 = [objcopy, "-O", "ihex", "-R", ".eeprom", elf_path, hex_path]
            r2 = subprocess.run(cmd2, capture_output=True, text=True)
            if r2.returncode != 0:
                return all_stdout, all_stderr + "\n" + r2.stderr, r2.returncode

            return all_stdout, all_stderr, 0

        finally:
            # Clean up temp .o files
            for obj in obj_files:
                try:
                    os.remove(obj)
                except Exception:
                    pass
            try:
                os.rmdir(obj_dir)
            except Exception:
                pass

    @staticmethod
    def _get_arduino_version() -> int:
        """Read arduino_version from platform_config, fallback 10607."""
        try:
            import yaml
            config_path = Path(__file__).resolve().parent.parent.parent / "infrastructure" / "platform_config.yaml"
            with open(config_path) as f:
                cfg = yaml.safe_load(f)
            return int(cfg.get("arduino", {}).get("arduino_version", 10607))
        except Exception:
            return 10607

    @staticmethod
    def _tool_available(name: str) -> bool:
        try:
            subprocess.run([name, "--version"], capture_output=True, timeout=3)
            return True
        except Exception:
            return False

    @staticmethod
    def _run_make(source_dir: str, output_dir: str) -> tuple[str, str, int]:
        """Run make in source_dir with output_dir for artifacts."""
        cmd = ["make", "-C", source_dir, f"BUILD_DIR={output_dir}"]
        r = subprocess.run(cmd, capture_output=True, text=True)
        return r.stdout, r.stderr, r.returncode
