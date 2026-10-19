"""STM32 BuildProvider —— arm-none-eabi-gcc 编译器适配（Cortex-M7 / GC-H743）。

与 AVR 路线的结构对应关系
--------------------------
================  ==========================  ==============================
环节                AVR 路线                     STM32 路线
================  ==========================  ==============================
编译器              avr-gcc                     arm-none-eabi-gcc
SDK                 ArduinoCore-avr（B 区）      HAL + CMSIS device（B 区）
预编译缓存           core.a                      hal.a（HAL+system+startup）
链接脚本            无（avrdude 只认 .hex）      `-T gc_h743.ld`（必需）
中间产物            全部丢弃                    保留 .elf（带符号，调试用）
================  ==========================  ==============================

**参数全部来自 `board.yaml` 的 `build:` 段**（参数是数据而非程序）：
SDK 版本、HAL 模块清单、FPU、优化级别、链接脚本、hal_conf 路径都在那里。
本文件只负责"把声明翻译成命令行"。

hal_conf.h 与 linker script 为什么在**板卡目录**里而不是 B 区
--------------------------------------------------------------
它们不是厂家原样物：`HSE_VALUE` 要按本板 25 MHz 改（官方模板是 NUCLEO 的
8 MHz）、内存布局要用满 512 KB AXI SRAM（官方模板只用 128 KB）、
`*_MODULE_ENABLED` 要按本板裁剪。删掉它们要重新写一遍 —— 属承诺级，
按标准 §5 R1 入 A 区。

降级行为
--------
工具链或 SDK 缺失时**不抛异常**，返回 `BuildResult(success=False)` 并把
「缺什么、装到哪、改哪个文件」写进 `stderr`。在导入期炸掉会让 `ff doctor`
连"缺什么"都报不出来。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from firmforge.core.resources import boards_dir
from firmforge.infrastructure import paths
from firmforge.providers.base import BuildDiagnostic, BuildProvider, BuildResult
from firmforge.providers.gcc_diagnostics import parse_gcc_diagnostics
from firmforge.providers.stm32.toolchain import Stm32Toolchain, resolve_toolchain

logger = logging.getLogger(__name__)

#: 用户源码扩展名 → 是否按 C++ 编译
_SOURCE_EXTS = (".c", ".cpp", ".cc", ".S", ".s")

#: `hal_modules` 条目 → hal_conf.h 的守卫宏名。
#: 多数情况下就是"大写"（`gpio` → `HAL_GPIO_MODULE_ENABLED`），但 `_ex` 后缀的
#: 实现文件由**基础模块**的守卫覆盖 —— `stm32h7xx_hal_rcc_ex.c` 的整文件被
#: `#if defined(HAL_RCC_MODULE_ENABLED)` 包着，没有 `HAL_RCC_EX_MODULE_ENABLED`。
_HAL_GUARD_ALIASES = {"rcc_ex": "rcc", "gpio_ex": "gpio", "adc_ex": "adc",
                      "dac_ex": "dac", "dma_ex": "dma", "pwr_ex": "pwr",
                      "tim_ex": "tim", "i2c_ex": "i2c", "uart_ex": "uart",
                      "usart_ex": "usart", "spi_ex": "spi", "flash_ex": "flash"}


def hal_module_guard(module: str) -> str:
    """`hal_modules` 条目 → `HAL_<GUARD>_MODULE_ENABLED` 里的 `<GUARD>`。"""
    return _HAL_GUARD_ALIASES.get(module, module).upper()


#: 只作用于 SDK 源码（HAL / CMSIS / startup）的编译参数。
#:
#: `-w`  —— HAL 是厂家代码，警告不是我们要处理的信号（与 AVR 路线对
#:          ArduinoCore 的 `-w` 同策）。用户代码仍然 `-Wall`。
#: `-g1` —— 覆盖 common_flags 里的 `-g3`。HAL 的完整调试信息让归档从几 MB
#:          涨到 30 MB，而真正要单步的是用户代码。行号表足够粗粒度定位。
#:
#: ⚠️ 这份清单**必须进缓存键** —— 改了它不重建归档，就会拿到用旧参数编的
#:    hal.a，且完全看不出来（内容哈希只覆盖源文件与 common_flags）。
_SDK_EXTRA_FLAGS = ("-w", "-g1")


@dataclass
class _SdkLayout:
    """解析后的 SDK 布局。`problems` 非空时其余字段可能不完整。"""

    device_root: Path | None = None
    hal_root: Path | None = None
    cmsis_core_root: Path | None = None
    board_dir: Path | None = None

    includes: list[str] = field(default_factory=list)
    startup: str = ""
    system: str = ""
    linker_script: str = ""
    hal_conf: str = ""
    hal_sources: list[str] = field(default_factory=list)

    problems: list[str] = field(default_factory=list)


class Stm32BuildProvider(BuildProvider):
    """STM32H7 compiler adapter (arm-none-eabi-gcc)."""

    def __init__(self, board_config: dict[str, Any]) -> None:
        super().__init__(board_config)
        self._toolchain: Stm32Toolchain = resolve_toolchain()
        self._build_cfg: dict[str, Any] = board_config.get("build", {}) or {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build(self, source_dir: str,
              output_dir: str | None = None) -> BuildResult:
        """编译 `source_dir` 下的用户源码 → firmware.hex / .bin / .elf。"""
        src = Path(source_dir).resolve()
        board_id = str(self._board_config.get("board_id", "") or "")
        out = paths.resolve_output_dir(src, output_dir,
                                       board_id=board_id, app_name=src.name)
        out.mkdir(parents=True, exist_ok=True)

        start = time.time()
        result = BuildResult(success=False)

        # -- 前置检查：缺什么就说清楚，别等到 subprocess 报 FileNotFound ----
        gate = self._preflight(src)
        if gate:
            result.stderr = gate
            result.errors = [BuildDiagnostic(severity="error",
                                             message=gate, raw=gate)]
            result.elapsed_ms = (time.time() - start) * 1000
            return result

        sdk = self._resolve_sdk()
        if sdk.problems:
            # 缺件在构建前报清楚，别让编译器替它报 —— 否则报出来的是
            # "fatal error: stm32h7xx_hal_conf.h: No such file or directory"，
            # 离真实原因（板卡目录没定位到）隔了好几层。与 AVR 路线同语义，
            # 见 _format_sdk_problems。
            result.stderr = self._format_sdk_problems(sdk.problems)
            result.errors = [BuildDiagnostic(severity="error",
                                             message=result.stderr,
                                             raw=result.stderr)]
            result.elapsed_ms = (time.time() - start) * 1000
            return result

        user_sources = self._collect_sources(src, out)
        if not user_sources:
            result.stderr = f"No source files {_SOURCE_EXTS} found in {src}"
            result.errors = [BuildDiagnostic(severity="error",
                                             file=str(src),
                                             message=result.stderr,
                                             raw=result.stderr)]
            result.elapsed_ms = (time.time() - start) * 1000
            return result

        firmware_elf = out / "firmware.elf"
        firmware_hex = out / "firmware.hex"

        try:
            stdout, stderr, rc = self._compile(user_sources, sdk,
                                               str(firmware_elf),
                                               str(firmware_hex), out)
            result.stdout, result.stderr = stdout, stderr
            result.success = rc == 0

            if result.success and firmware_hex.exists():
                result.firmware_path = str(firmware_hex)
                result.stdout += self._size_report(str(firmware_elf))
            elif stderr:
                result.errors = self.parse_build_errors(stderr)
            return result
        finally:
            result.elapsed_ms = (time.time() - start) * 1000

    def parse_build_errors(self, stderr: str) -> list[BuildDiagnostic]:
        """arm-none-eabi-gcc 诊断格式与 avr-gcc 同源，走共用解析。"""
        return parse_gcc_diagnostics(stderr)

    def get_toolchain_version(self) -> str:
        from firmforge.providers.stm32.toolchain import version_of
        return version_of(self._toolchain.gcc)

    # ------------------------------------------------------------------
    # SDK 与板级文件解析
    # ------------------------------------------------------------------

    def _resolve_sdk(self) -> _SdkLayout:
        """按 `board.yaml::build.sdk` 定位三件套与板级文件。"""
        lay = _SdkLayout()
        pkg_root = paths.packages_dir() / "stm32"

        def _pkg(key: str) -> Path | None:
            spec = (self._build_cfg.get("sdk", {}) or {}).get(key) or {}
            name, ver = spec.get("package"), spec.get("version")
            if not name or not ver:
                lay.problems.append(f"board.yaml 缺少 build.sdk.{key}")
                return None
            root = pkg_root / str(name) / str(ver)
            if not root.is_dir():
                repo = spec.get("repo") or f"STMicroelectronics/{name}"
                lay.problems.append(
                    f"SDK 未安装：{root}\n"
                    f"    下载解包到该目录即可（仓库 {repo}，tag v{ver}）：\n"
                    f"    https://codeload.github.com/{repo}/zip/refs/tags/v{ver}")
                return None
            return root

        lay.device_root = _pkg("device")
        lay.hal_root = _pkg("hal")
        lay.cmsis_core_root = _pkg("cmsis_core")

        board_id = str(self._board_config.get("board_id", "") or "")
        board_dir: Path | None = None
        if not board_id:
            # 正常路径下 board_id 由 BoardDetector.resolve_board() 注入（唯一
            # 注入点）；走到这里说明 provider 是被直接构造的，缺板卡身份。
            lay.problems.append(
                "配置缺少 board_id —— 板级文件（链接脚本 / hal_conf.h / "
                "include/）无法定位。经管道或 resolve_board() 取配置即可避免。")
        else:
            board_dir = boards_dir() / board_id
            if not board_dir.is_dir():
                lay.problems.append(f"板卡目录不存在：{board_dir}")
                board_dir = None
            else:
                lay.board_dir = board_dir

        # -- 板级文件（相对板卡目录）--------------------------------------
        for attr, key in (("linker_script", "linker_script"),
                          ("hal_conf", "hal_conf")):
            rel = self._build_cfg.get(key)
            if not rel:
                lay.problems.append(f"board.yaml 缺少 build.{key}")
                continue
            path = board_dir / str(rel) if board_dir else None
            if not path or not path.is_file():
                lay.problems.append(f"板级文件缺失：{path}")
                continue
            setattr(lay, attr, str(path))

        # -- CMSIS 器件文件 ------------------------------------------------
        if lay.device_root:
            for attr, key in (("startup", "startup"), ("system", "system")):
                rel = self._build_cfg.get(key)
                if not rel:
                    lay.problems.append(f"board.yaml 缺少 build.{key}")
                    continue
                path = lay.device_root / str(rel)
                if not path.is_file():
                    lay.problems.append(f"CMSIS 器件文件缺失：{path}")
                    continue
                setattr(lay, attr, str(path))

        # -- 头文件搜索路径 ------------------------------------------------
        if lay.device_root:
            lay.includes.append(str(lay.device_root / "Include"))
        if lay.hal_root:
            lay.includes.append(str(lay.hal_root / "Inc"))
        if lay.cmsis_core_root:
            lay.includes.append(str(lay.cmsis_core_root / "CMSIS" / "Core" / "Include"))
        if lay.board_dir:
            lay.includes.append(str(lay.board_dir / "include"))

        # -- HAL 源文件 ----------------------------------------------------
        if lay.hal_root:
            lay.hal_sources = self._hal_sources(lay.hal_root)

        return lay

    def _hal_sources(self, hal_root: Path) -> list[str]:
        """`hal_modules` → `Src/stm32h7xx_hal_<m>.c`，另外总是带上 hal.c。

        展开规则写在这里而不是让 board.yaml 逐条列文件名，是为了让
        board.yaml 保持"人读得懂"；代价是这条规则必须与 HAL 仓库的命名
        保持一致（`rcc_ex` → `stm32h7xx_hal_rcc_ex.c`）。清单与 hal_conf.h
        的 `*_MODULE_ENABLED` 必须一致 —— `tests/test_stm32_provider.py` 守着。
        """
        src_dir = hal_root / "Src"
        out: list[str] = []
        core = src_dir / "stm32h7xx_hal.c"
        if core.is_file():
            out.append(str(core))
        for module in self._build_cfg.get("hal_modules", []) or []:
            candidate = src_dir / f"stm32h7xx_hal_{module}.c"
            if candidate.is_file():
                out.append(str(candidate))
            else:
                logger.warning("HAL module source not found: %s", candidate)
        return out

    def _preflight(self, src: Path) -> str:
        """返回空串表示可以开始编译；否则返回可操作的错误说明。"""
        problems = list(self._toolchain.problems())
        if problems:
            return "STM32 工具链不完整：\n  - " + "\n  - ".join(problems)
        if not src.is_dir():
            return f"Source directory not found: {src}"
        return ""

    @staticmethod
    def _format_sdk_problems(problems: list[str]) -> str:
        """SDK / 板级文件不完整时给出可操作说明。

        与 AVR 路线同语义：`arduino/build.py` 里 avr-gcc 缺失、`Arduino.h`
        找不到，都是在构建前直接返回一句"缺什么、怎么办"。区别只是 STM32
        一次性解析三件套 + 板级文件，所以把 AVR 的多处内联检查合并成
        一次消费 `_SdkLayout.problems`。
        """
        return "STM32 SDK / 板级文件不完整：\n  - " + "\n  - ".join(problems)

    # ------------------------------------------------------------------
    # 编译
    # ------------------------------------------------------------------

    def _common_flags(self, sdk: _SdkLayout) -> list[str]:
        fpu = self._build_cfg.get("fpu", "fpv5-d16")
        abi = self._build_cfg.get("float_abi", "hard")
        flags = ["-mcpu=cortex-m7", "-mthumb",
                 f"-mfpu={fpu}", f"-mfloat-abi={abi}"]
        flags += [f"-D{d}" for d in self._build_cfg.get("defines", []) or []]
        flags += [f"-I{p}" for p in sdk.includes]
        flags += ["-ffunction-sections", "-fdata-sections", "-fno-common"]
        # newlib-nano + 无系统 syscall 桩：裸机不需要 OS，缺 _write 等符号
        # 会变成链接错误，--specs=nosys.specs 提供弱桩。
        flags += ["--specs=nano.specs", "--specs=nosys.specs"]
        flags += [self._build_cfg.get("optimize", "-Og"), "-g3"]
        # 浮点 printf 在 newlib-nano 默认关闭（省 ~10 KB）；本板用得到时
        # 在 board.yaml 里加 build.extra_link_flags: ["-u", "_printf_float"]。
        flags += list(self._build_cfg.get("extra_compile_flags", []) or [])
        return flags

    def _compile(self, user_sources: list[str], sdk: _SdkLayout,
                 elf_path: str, hex_path: str,
                 out: Path) -> tuple[str, str, int]:
        gcc = self._toolchain.gcc
        gpp = self._toolchain.gpp or gcc
        objcopy = self._toolchain.objcopy
        common = self._common_flags(sdk)
        stdout_all = ""
        stderr_all = ""

        # -- Step 1: SDK 归档（HAL + system + startup），带内容哈希缓存 ----
        archive_path, sdk_out, sdk_err, sdk_rc = self._build_sdk_archive(sdk, common)
        stdout_all += sdk_out
        stderr_all += sdk_err
        if archive_path is None:
            return stdout_all, stderr_all, sdk_rc or 1
        stdout_all += f"\n[sdk] {Path(archive_path).name} ready\n"

        # -- Step 2: 用户源码 → .o（临时目录，编完即删）-------------------
        obj_dir = tempfile.mkdtemp(prefix="ff_stm32_")
        user_objs: list[str] = []
        try:
            for i, src in enumerate(user_sources):
                obj = os.path.join(obj_dir, f"{i:03d}.o")
                is_cpp = src.endswith((".cpp", ".cc"))
                compiler = gpp if is_cpp else gcc
                lang = (["-std=" + self._build_cfg.get("cpp_standard", "gnu++17")]
                        if is_cpp else
                        ["-std=" + self._build_cfg.get("c_standard", "gnu11")])
                cmd = ([compiler] + common + ["-Wall"] + lang
                       + ["-c", "-o", obj, src])
                logger.info("Compile[%d/%d]: %s", i + 1, len(user_sources), src)
                r = subprocess.run(cmd, capture_output=True, text=True)
                stdout_all += r.stdout
                stderr_all += r.stderr
                if r.returncode != 0:
                    return stdout_all, stderr_all, r.returncode
                user_objs.append(obj)

            # -- Step 3: 链接 -------------------------------------------------
            # 链接用 g++ 驱动：C++ 运行时（全局构造、new/delete）由它带上；
            # 纯 C 工程也安全（g++ 会自行决定是否引入 libstdc++）。
            map_path = str(out / "firmware.map")
            link_cmd = [gpp] + common + [
                f"-T{sdk.linker_script}",
                f"-Wl,-Map={map_path}",
                "-Wl,--gc-sections",
                "-o", elf_path,
            ] + user_objs + [archive_path] + [
                "-Wl,--start-group", "-lc", "-lm", "-lgcc", "-Wl,--end-group",
            ] + list(self._build_cfg.get("extra_link_flags", []) or [])
            logger.info("Link: %s", " ".join(link_cmd))
            r = subprocess.run(link_cmd, capture_output=True, text=True)
            stdout_all += r.stdout
            stderr_all += r.stderr
            if r.returncode != 0:
                return stdout_all, stderr_all, r.returncode

            # -- Step 4: .elf → .hex / .bin -----------------------------------
            for args, target in ((("-O", "ihex"), hex_path),
                                 (("-O", "binary"), str(out / "firmware.bin"))):
                r2 = subprocess.run([objcopy, *args, elf_path, target],
                                    capture_output=True, text=True)
                if r2.returncode != 0:
                    return stdout_all, stderr_all + r2.stderr, r2.returncode
            return stdout_all, stderr_all, 0
        finally:
            shutil.rmtree(obj_dir, ignore_errors=True)

    # -- SDK 归档缓存 ----------------------------------------------------

    def _sdk_cache_dir(self, sdk: _SdkLayout) -> Path:
        sdk_spec = self._build_cfg.get("sdk", {}) or {}
        hal_ver = (sdk_spec.get("hal", {}) or {}).get("version", "unknown")
        dev_ver = (sdk_spec.get("device", {}) or {}).get("version", "unknown")
        mcu = str(self._board_config.get("mcu", {}).get("chip", "unknown")).lower()
        return paths.sdk_cache_dir() / "stm32" / f"{hal_ver}_{dev_ver}" / mcu

    def _sdk_archive(self, sdk: _SdkLayout, common_flags: list[str]) -> str | None:
        """若缓存有效，返回现成 hal.a 路径；否则 None（需要重建）。"""
        if not sdk.hal_root:
            return None
        cache = self._sdk_cache_dir(sdk)
        archive = cache / "hal.a"
        # 声明文件统一叫 lock.json（派生物，标准 §5.2）；旧缓存的
        # manifest.json 仍可读，下次重建即改名，不会让旧缓存白丢一次。
        lock_file = cache / "lock.json"
        if not lock_file.is_file():
            lock_file = cache / "manifest.json"
        if not archive.is_file() or not lock_file.is_file():
            return None
        try:
            manifest = json.loads(lock_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if manifest.get("__key__") != self._sdk_cache_key(sdk, common_flags):
            return None
        return str(archive)

    def _sdk_cache_key(self, sdk: _SdkLayout, common_flags: list[str]) -> str:
        """SHA256(全部 SDK 源内容 + 编译参数 + 链接脚本 + hal_conf + 工具链版本)。

        为什么把链接脚本和 hal_conf 也放进键里：它们决定 `-T` 的布局与
        `*_MODULE_ENABLED`，改了它们必须重编 HAL —— 否则会出现
        「改了 hal_conf 没生效」这种查不出的幽灵 bug（标准 §5 R6 的理由）。
        """
        h = hashlib.sha256()
        for flag in common_flags:
            h.update(flag.encode("utf-8"))
        for flag in _SDK_EXTRA_FLAGS:
            h.update(flag.encode("utf-8"))
        for path in (sdk.linker_script, sdk.hal_conf, sdk.system, sdk.startup):
            if path and Path(path).is_file():
                h.update(Path(path).read_bytes())
        for src in sdk.hal_sources:
            h.update(Path(src).read_bytes())
        h.update(self.get_toolchain_version().encode("utf-8"))
        return h.hexdigest()

    def _build_sdk_archive(
        self, sdk: _SdkLayout, common_flags: list[str],
    ) -> tuple[str | None, str, str, int]:
        """编译或复用 SDK 归档。返回 (hal.a 路径或 None, stdout, stderr, rc)。"""
        cached = self._sdk_archive(sdk, common_flags)
        if cached:
            logger.info("SDK archive cache hit: %s", cached)
            return cached, "", "", 0

        gcc = self._toolchain.gcc
        gpp = self._toolchain.gpp or gcc
        sources: list[str] = []
        for p in (sdk.startup, sdk.system):
            if p:
                sources.append(p)
        sources += sdk.hal_sources

        cache = self._sdk_cache_dir(sdk)
        cache.mkdir(parents=True, exist_ok=True)
        archive = cache / "hal.a"
        stdout_all = stderr_all = ""
        objs: list[str] = []
        tmp = tempfile.mkdtemp(prefix="ff_stm32_sdk_")
        try:
            for i, src in enumerate(sources):
                obj = os.path.join(tmp, f"{i:03d}.o")
                suffix = Path(src).suffix.lower()
                if suffix == ".s":
                    cmd = ([gcc] + common_flags + list(_SDK_EXTRA_FLAGS)
                           + ["-x", "assembler-with-cpp", "-c", "-o", obj, src])
                else:
                    compiler = gpp if suffix in (".cpp", ".cc") else gcc
                    cmd = ([compiler] + common_flags + list(_SDK_EXTRA_FLAGS)
                           + ["-c", "-o", obj, src])
                logger.info("SDK compile[%d/%d]: %s", i + 1, len(sources),
                            Path(src).name)
                r = subprocess.run(cmd, capture_output=True, text=True)
                stdout_all += r.stdout
                stderr_all += r.stderr
                if r.returncode != 0:
                    logger.warning("SDK compile failed: %s", src)
                    return None, stdout_all, stderr_all, r.returncode
                objs.append(obj)

            if archive.exists():
                archive.unlink()     # arm-ar rcs 会追加，必须先删
            ar = str(Path(gcc).with_name(
                "arm-none-eabi-ar.exe" if os.name == "nt" else "arm-none-eabi-ar"))
            r = subprocess.run([ar, "rcs", str(archive), *objs],
                               capture_output=True, text=True)
            stdout_all += r.stdout
            stderr_all += r.stderr
            if r.returncode != 0:
                return None, stdout_all, stderr_all, r.returncode

            # 写 lock.json（派生物声明文件，标准 §5.2），并清掉旧名
            lock_path = cache / "lock.json"
            lock_path.write_text(json.dumps({
                "schema": "cache/lock/v1",
                "kind": "derived",
                "generator": "firmforge.providers.stm32.build",
                "__key__": self._sdk_cache_key(sdk, common_flags),
                "__sources__": len(sources),
                "__toolchain__": self.get_toolchain_version(),
            }, indent=2), encoding="utf-8")
            legacy = cache / "manifest.json"
            if legacy.is_file():
                legacy.unlink()
            return str(archive), stdout_all, stderr_all, 0
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------

    @staticmethod
    def _collect_sources(src: Path, out: Path) -> list[str]:
        """收集用户源码，排除构建产物目录（两者可能重叠，见 resolve_output_dir）。"""
        found: list[str] = []
        for path in sorted(src.rglob("*")):
            if not path.is_file() or path.suffix not in _SOURCE_EXTS:
                continue
            try:
                path.resolve().relative_to(out.resolve())
                continue          # 跳过构建输出目录内的内容
            except ValueError:
                pass
            found.append(str(path))
        return found

    def _size_report(self, elf_path: str) -> str:
        size = self._toolchain.size
        if not size or not Path(elf_path).is_file():
            return ""
        try:
            r = subprocess.run([size, elf_path], capture_output=True,
                               text=True, timeout=20)
            return "\n[size]\n" + (r.stdout or r.stderr)
        except (OSError, subprocess.SubprocessError):
            return ""


__all__ = ["Stm32BuildProvider", "hal_module_guard"]
