"""FirmForge 路径解析 —— 全项目唯一真源。

分区判据见 `docs/路径分区标准.md`：不问「放哪个区」，只问
「删掉它，要做什么才能恢复？」——五个答案对应五类生命周期。

两个根：

  A 区（项目内，由工作区决定）
      承诺级  committed   源码 / board.yaml / schema / 生成器     → 入库
      运行时  runtime     `<workspace>/.ff-run/`（会话级产物）    → 不入库

  B 区（用户级，`~/.firmforge/`）
      厂家物  vendor      toolchains/ packages/ examples/ sources/
      派生物  derived     cache/
      用户态  user-state  config/

环境变量
--------
`FIRMFORGE_HOME` 覆盖 B 区根（默认 `~/.firmforge`）。用于 CI / 沙箱：
`FIRMFORGE_HOME=/tmp/ff ff build ...` 可得到完全干净的隔离环境。

命名规约
--------
项目内运行时目录名是 `.ff-run`，**不得**叫 `.firmforge` —— 与用户级
`~/.firmforge/` 同名会造成「同名不同物」的排查陷阱（标准 §1 证据 #1）。
"""

from __future__ import annotations

import os
from pathlib import Path

# --------------------------------------------------------------------------
# 常量
# --------------------------------------------------------------------------

#: 项目内运行时目录名（带 `.` 前缀，满足 N2；不得与用户级根同名，满足 N1）
RUNTIME_DIR_NAME = ".ff-run"

#: 用户级根目录名
USER_HOME_DIR_NAME = ".firmforge"


# --------------------------------------------------------------------------
# B 区（用户级根）
# --------------------------------------------------------------------------

def firmforge_home() -> Path:
    """B 区根目录。`FIRMFORGE_HOME` 环境变量优先，否则 `~/.firmforge`。"""
    override = os.environ.get("FIRMFORGE_HOME", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return Path.home() / USER_HOME_DIR_NAME


def toolchains_dir() -> Path:
    """厂家工具链二进制（avr-gcc / avrdude / cppcheck / arm-none-eabi-gcc ...）。"""
    return firmforge_home() / "toolchains"


def packages_dir() -> Path:
    """平台 SDK（ArduinoCore-avr / STM32 HAL+Device ...）。"""
    return firmforge_home() / "packages"


def cache_dir() -> Path:
    """派生物根目录（构建产物 + 知识库生成结果 + 预处理中间文件）。"""
    return firmforge_home() / "cache"


# --------------------------------------------------------------------------
# 芯片数据的目录分级：<平台>/<系列>/<芯片>
# --------------------------------------------------------------------------

def series_scope(platform: str, series: str | None) -> tuple[str, ...]:
    """芯片数据的层前缀：``("<平台>",)`` 或 ``("<平台>", "<系列>")``。

    同一平台下会有多代芯片系列（STM32H7 / STM32F1 / STM32F4 …），
    它们的寄存器手册、SVD、HAL 版本互不相同。全部平铺在
    ``<平台>/<芯片>/`` 时，"H7 和 F1 是不同的东西"这件事只存在于人脑里；
    一旦哪天两个系列有同型号后缀或同版本号，就会安静地互相覆盖。
    所以凡按芯片存放的数据目录一律三级，**芯片目录的父目录永远是系列**。

    系列与平台同名时折叠一级：AVR 只有一个系列（``avr``），
    路径仍是 ``avr/atmega2560/``，不制造 ``avr/avr/atmega2560/`` 这种空层。
    """
    plat = platform.strip().lower()
    ser = (series or "").strip().lower()
    if not ser or ser == plat:
        return (plat,)
    return (plat, ser)


def scoped_chip_dir(root: Path | str, platform: str, series: str | None,
                    chip: str) -> Path:
    """拼出 ``<root>/<平台>[/<系列>]/<芯片>``。芯片名统一小写。"""
    return Path(root).joinpath(*series_scope(platform, series), chip.strip().lower())


def examples_dir() -> Path:
    """官方示例库（benchmark 料源）。"""
    return firmforge_home() / "examples"


def config_dir() -> Path:
    """用户态配置（llm.yaml 等，含密钥，绝不入库）。"""
    return firmforge_home() / "config"


def sources_dir() -> Path:
    """厂家原始数据（SVD / io*.h / avrdude.conf / OpenOCD cfg）。

    知识库生成器的**输入原料**。放 B 区是因为它们是厂家给的、
    可重新下载的通用数据，不含任何项目自定规则。
    """
    return firmforge_home() / "sources"


# --------------------------------------------------------------------------
# 派生物子路径
# --------------------------------------------------------------------------

def build_cache_dir() -> Path:
    """用户代码构建产物：`cache/build/<board>/<app>/firmware.hex`。"""
    return cache_dir() / "build"


def sdk_cache_dir() -> Path:
    """SDK 预编译缓存：`cache/sdk/<platform>/<sdk>/<version>/<mcu>/core.a`。

    与 `packages/` 分离的理由（标准 §5 R6 / §10.3 第 8 项）：
    `packages/` 语义是「厂家物，可整块删除重下」，而 `core.a` 删掉要重编
    55 秒 —— 生命周期不同，不能同处一室。
    """
    return cache_dir() / "sdk"


def preprocess_cache_dir() -> Path:
    """`.ino` 预处理中间文件。"""
    return cache_dir() / "preprocess"


def knowledge_cache_dir() -> Path:
    """知识库生成结果缓存：`cache/knowledge/<platform>/<chip>/`。

    旁边必须放 `lock.json`（源哈希 + 生成器版本 + override 哈希 + 输出哈希），
    否则「改了规则没生效」会变成查不出的幽灵 bug。
    """
    return cache_dir() / "knowledge"


# --------------------------------------------------------------------------
# A 区（项目内）
# --------------------------------------------------------------------------

def find_project_root(start: Path | str | None = None) -> Path | None:
    """向上查找含 `.git` 的目录。找不到返回 None。"""
    cur = Path(start or os.getcwd()).resolve()
    for candidate in (cur, *cur.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def is_inside_project(path: Path | str) -> bool:
    """路径是否位于某个 git 工作区内（= 属于 A 区）。"""
    p = Path(path).resolve()
    return find_project_root(p if p.is_dir() else p.parent) is not None


def runtime_dir(workspace: Path | str) -> Path:
    """项目内运行时目录：`<workspace>/.ff-run/`。

    state.json / ledger.jsonl / serial_live.html / goto_panel.html 等
    会话级产物都落这里。删除它不影响功能 —— 只会丢失增量缓存。
    """
    return Path(workspace) / RUNTIME_DIR_NAME


def resolve_output_dir(source_dir: Path | str,
                       output_dir: Path | str | None = None,
                       board_id: str = "",
                       app_name: str = "") -> Path:
    """决定构建产物落点，并阻止污染 A 区源码树。

    规则：
      1. 显式传入 `output_dir` → 原样使用（调用方负责）。
      2. 未传入，且 `source_dir` 位于项目内 → **重定向到 B 区**
         `cache/build/<board>/<app>/`。
      3. 未传入，且 `source_dir` 在项目外（如 tmp_path）→ 落 source_dir，
         保持单元测试与临时编译的直觉行为。

    规则 2 是硬防线：源码目录里出现 `firmware.hex` 属于标准 §5 R2 违规
    （派生物物理位于 A 区），而调用方忘传 `output_dir` 是常见失误。
    """
    if output_dir is not None:
        return Path(output_dir).resolve()

    src = Path(source_dir).resolve()
    if is_inside_project(src):
        board = board_id or "unknown"
        app = app_name or src.name
        return (build_cache_dir() / board / app).resolve()

    return src


# --------------------------------------------------------------------------
# 骨架
# --------------------------------------------------------------------------

#: B 区应有的顶层子树（顺序即创建顺序）
_B_HOME_SUBTREES = ("toolchains", "packages", "cache", "examples", "config", "sources")

#: B 区 cache 下的子目录
_CACHE_SUBTREES = ("build", "sdk", "preprocess", "knowledge")


def ensure_layout(verbose: bool = False) -> list[Path]:
    """创建 B 区骨架目录。幂等。返回本次创建（或已存在）的路径列表。"""
    created: list[Path] = []
    home = firmforge_home()
    for name in _B_HOME_SUBTREES:
        p = home / name
        p.mkdir(parents=True, exist_ok=True)
        created.append(p)
    for name in _CACHE_SUBTREES:
        p = home / "cache" / name
        p.mkdir(parents=True, exist_ok=True)
        created.append(p)
    return created


def describe() -> dict[str, str]:
    """返回当前生效的路径映射，供 `ff doctor` / `ff context` 输出。

    用户看不到「数据从哪来」是分区的已知代价，这个函数是补偿手段。
    """
    return {
        "user_home": str(firmforge_home()),
        "toolchains": str(toolchains_dir()),
        "packages": str(packages_dir()),
        "cache_build": str(build_cache_dir()),
        "cache_sdk": str(sdk_cache_dir()),
        "cache_knowledge": str(knowledge_cache_dir()),
        "examples": str(examples_dir()),
        "config": str(config_dir()),
        "sources": str(sources_dir()),
        "runtime_dir_name": RUNTIME_DIR_NAME,
        "env_override": os.environ.get("FIRMFORGE_HOME", ""),
    }
