#!/usr/bin/env python3
"""check_layout.py — FirmForge 路径与产物分区标准校验器

依据 docs/路径分区标准.md 的 R1–R8 硬规则，对仓库与用户级目录做静态校验。

用法:
    python scripts/check_layout.py            # 人类可读输出
    python scripts/check_layout.py --json     # 纯 JSON 出 stdout
    python scripts/check_layout.py --strict   # WARN 也算失败

退出码:
    0 = 无 ERROR
    1 = 存在 ERROR
    2 = 环境错误（不在 git 仓库内等）
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

# --------------------------------------------------------------------------
# 模式表：本标准 §5 归属矩阵的可执行形式
# --------------------------------------------------------------------------

# §5 #1/#2 —— 承诺级：必须在项目内且入库
# 注意：docs/ 不在表内。2026-10-21 决定整目录不入库 —— 里面是规划、选型论证、
# 分区标准、benchmark 数据等开发期资料，与代码库无关，不该出现在公开仓库里。
# 因此 docs/ 既不是承诺级、也不参与 R1；本地保留，由 .gitignore 覆盖。
COMMITTED_DIR_PREFIXES = (
    "firmforge/adapters/",
    "firmforge/core/",
    "firmforge/infrastructure/",
    "firmforge/knowledge/",
    "firmforge/providers/",
    "firmforge/tools/",
    "firmforge/data/boards/",
    "firmforge/data/vendor/manifests/",
    "tests/",
    "scripts/",
)

COMMITTED_TOP_FILES = (
    "pyproject.toml",
    "ff.cmd",
    "ff.ps1",
    "README.md",
    "README_CN.md",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "LICENSE",
    ".gitignore",
)

# §3.1 ① —— 例外条款：小体积 + 开箱即需 + 重建需外部下载 的派生物，允许入库
DERIVED_EXCEPTION_PREFIXES = ("firmforge/data/knowledge/reference/",)
DERIVED_EXCEPTION_MAX_BYTES = 512 * 1024  # 单芯片集 ≤ 512 KB

# §5.1 —— 派生物禁止入库的扩展名
DERIVED_FORBIDDEN_SUFFIXES = (".hex", ".elf", ".o", ".a", ".bin", ".map", ".d")

# §4.3 N1 —— 项目内目录名与用户级目录名不得相同
USER_HOME_DEFAULT = Path.home() / ".firmforge"

# §5 —— 用户级子树的期望生命周期
# 派生物统一收在 cache/ 下（build / sdk / preprocess / knowledge），顶层不再
# 单列 —— 见 docs/路径分区标准.md §5 决策树。
USER_VENDOR_SUBTREES = ("toolchains", "packages", "examples", "sources")
USER_DERIVED_SUBTREES = ("cache",)
USER_STATE_SUBTREES = ("config", "state")
USER_RUNTIME_SUBTREES = ("run", "tmp")
USER_REGISTERED_SUBTREES = (
    *USER_VENDOR_SUBTREES,
    *USER_DERIVED_SUBTREES,
    *USER_STATE_SUBTREES,
    *USER_RUNTIME_SUBTREES,
)

# §4.3 N2 —— 项目内运行时目录必须带 "." 前缀
PROJECT_RUNTIME_MARKERS = (".ff-run", ".workbuddy")
PROJECT_RUNTIME_LEGACY = (".firmforge",)  # 待整改：与用户级同名

# §5.2 —— 需要声明文件的生命周期
MANIFEST_NAMES = ("manifest.yaml", "manifest.yml", "manifest.json")
LOCK_NAMES = ("lock.json", ".lock.json")


# --------------------------------------------------------------------------
# 基础设施
# --------------------------------------------------------------------------


class Report:
    def __init__(self) -> None:
        self.errors: list[dict[str, str]] = []
        self.warnings: list[dict[str, str]] = []
        self.infos: list[dict[str, str]] = []

    def error(self, rule: str, item: str, detail: str) -> None:
        self.errors.append({"rule": rule, "item": item, "detail": detail})

    def warn(self, rule: str, item: str, detail: str) -> None:
        self.warnings.append({"rule": rule, "item": item, "detail": detail})

    def info(self, rule: str, item: str, detail: str) -> None:
        self.infos.append({"rule": rule, "item": item, "detail": detail})

    def ok(self) -> bool:
        return not self.errors


def run_git(args: list[str], cwd: Path) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return proc.returncode, proc.stdout
    except FileNotFoundError:
        return 127, ""


def find_repo_root(start: Path) -> Path | None:
    code, out = run_git(["rev-parse", "--show-toplevel"], start)
    if code != 0 or not out.strip():
        return None
    return Path(out.strip())


def git_tracked(root: Path) -> set[str]:
    code, out = run_git(["ls-files"], root)
    if code != 0:
        return set()
    return {line.strip().replace("\\", "/") for line in out.splitlines() if line.strip()}


def user_home() -> Path:
    override = os.environ.get("FIRMFORGE_HOME")
    return Path(override) if override else USER_HOME_DEFAULT


def dir_size(path: Path) -> int:
    total = 0
    for p in path.rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
        except OSError:
            continue
    return total


# 扫描项目内文件时剪掉的目录（版本控制 / 第三方工具 / 运行时 / 缓存）
SKIP_DIR_NAMES = frozenset(
    {
        ".git",
        ".workbuddy",
        ".firmforge",
        ".ff-run",
        ".venv",
        "__pycache__",
        ".pytest_cache",
        "node_modules",
    }
)


def iter_project_files(root: Path):
    """遍历项目内文件，剪掉版本控制 / 第三方工具 / 运行时目录。"""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d
            for d in dirnames
            if d not in SKIP_DIR_NAMES and not d.endswith(".egg-info")
        ]
        for fn in filenames:
            yield Path(dirpath) / fn


# --------------------------------------------------------------------------
# R1 —— 承诺级必须落在项目内且入库
# --------------------------------------------------------------------------


def check_r1(root: Path, tracked: set[str], rep: Report) -> None:
    for prefix in COMMITTED_DIR_PREFIXES:
        d = root / prefix
        if not d.is_dir():
            continue
        any_tracked = any(t.startswith(prefix) for t in tracked)
        if not any_tracked:
            rep.error("R1", prefix, "承诺级目录在 git 中无任何跟踪文件（仓库不自足）")

    for name in COMMITTED_TOP_FILES:
        f = root / name
        if f.exists() and name not in tracked:
            rep.error("R1", name, "承诺级顶层文件未入库")


# --------------------------------------------------------------------------
# R2 —— 派生物默认不入库；入库须满足例外条款
# --------------------------------------------------------------------------


def check_r2(root: Path, tracked: set[str], rep: Report) -> None:
    for rel in sorted(tracked):
        if not rel.endswith(DERIVED_FORBIDDEN_SUFFIXES):
            continue
        if rel.startswith(DERIVED_EXCEPTION_PREFIXES):
            continue
        rep.error("R2", rel, f"派生物扩展名 {Path(rel).suffix} 不应入库")

    # 例外条款的体积上限
    for prefix in DERIVED_EXCEPTION_PREFIXES:
        d = root / prefix
        if not d.is_dir():
            continue
        size = dir_size(d)
        if size > DERIVED_EXCEPTION_MAX_BYTES:
            rep.error(
                "R2",
                prefix,
                f"例外条款目录累计 {size} B 超上限 {DERIVED_EXCEPTION_MAX_BYTES} B",
            )
        else:
            rep.info("R2", prefix, f"例外条款目录累计 {size} B，在上限内")

    # 派生物物理存在于项目内目录（§5.1 非法组合 2 的现场）
    for p in iter_project_files(root):
        suffix = p.suffix.lower()
        if suffix not in (".hex", ".elf", ".o", ".a", ".bin", ".map"):
            continue
        rel = p.relative_to(root).as_posix()
        rep.warn(
            "R2",
            rel,
            "派生物物理位于项目内目录（应清理，见标准 §10.3 P1）",
        )


# --------------------------------------------------------------------------
# R3 —— 厂家物放用户级并带 manifest
# --------------------------------------------------------------------------


def check_r3(rep: Report) -> None:
    home = user_home()
    if not home.is_dir():
        rep.info("R3", str(home), "用户级目录不存在（尚未 ff setup），跳过")
        return
    for sub in USER_VENDOR_SUBTREES:
        d = home / sub
        if not d.is_dir():
            continue
        has_manifest = any((d / n).exists() for n in MANIFEST_NAMES)
        if not has_manifest:
            rep.warn("R3", f"~/.firmforge/{sub}/", "vendor 子树缺 manifest 声明文件")
        else:
            rep.info("R3", f"~/.firmforge/{sub}/", "manifest 存在")


# --------------------------------------------------------------------------
# R4 —— 项目内与用户级不得同名（N1）
# --------------------------------------------------------------------------


def check_r4(root: Path, rep: Report) -> None:
    """N1：项目内目录名不得与用户级根目录名相同。

    注意比对层级：用户级是 ``~/.firmforge/``（根目录名 ``.firmforge``），
    其子目录是 ``cache/`` ``config/`` 等。真正冲突的是**根目录名**。
    """
    home = user_home()
    user_root_name = home.name  # 例如 ".firmforge"

    for child in root.iterdir():
        if not child.is_dir():
            continue
        if child.name == user_root_name:
            rep.error(
                "R4",
                child.name,
                f"项目内目录与用户级根目录 ~/{user_root_name} 同名（违反 N1）",
            )

    # 反向：用户级子目录若与项目内顶层目录同名，同样会造成误读
    if home.is_dir():
        proj_names = {p.name for p in root.iterdir() if p.is_dir()}
        for sub in home.iterdir():
            if sub.is_dir() and sub.name in proj_names:
                rep.warn(
                    "R4",
                    f"~/{user_root_name}/{sub.name}",
                    f"与项目内顶层目录 {sub.name} 同名，建议消歧",
                )


# --------------------------------------------------------------------------
# R5 —— 运行时目录加 "." 前缀
# --------------------------------------------------------------------------


def check_r5(root: Path, rep: Report) -> None:
    """N2：运行时目录必须带 "." 前缀。"""
    for marker in PROJECT_RUNTIME_MARKERS:
        if (root / marker).is_dir():
            rep.info("R5", marker, "运行时目录命名合规（带 . 前缀）")

    # 注意：".firmforge" 本身**满足** N2（带 . 前缀），它违反的是 N1 同名——
    # 该冲突由 R4 报 ERROR，此处只作整改提示，避免同一问题重复计数。
    for legacy in PROJECT_RUNTIME_LEGACY:
        if (root / legacy).is_dir():
            rep.warn(
                "R5",
                legacy,
                "命名满足 N2，但与用户级同名（N1 违反，见 R4），建议改名 .ff-run/",
            )


# --------------------------------------------------------------------------
# R6 —— 每个 derived 目录必须带 lock.json
# --------------------------------------------------------------------------


def _derived_leaf_dirs(cache: Path) -> list[tuple[Path, str]]:
    """找出**实际承载派生产物**的目录，返回 (目录, 产物说明)。

    R6 的判据必须落在产物那一层，不是 `cache/` 根：`cache/` 只是容器，
    它自己永远不会有一个 lock.json，按根判会永远报同一条无意义的警告。
    """
    leaves: list[tuple[Path, str]] = []

    # 知识库：cache/knowledge/<platform>/<chip>/{registers,pins}.json
    kb = cache / "knowledge"
    if kb.is_dir():
        for d in sorted(kb.rglob("*")):
            if d.is_dir() and any((d / n).is_file()
                                  for n in ("registers.json", "pins.json")):
                leaves.append((d, "知识库数据"))

    # SDK 编译缓存：缓存单元是含静态库（core.a / hal.a）的那一级；
    # 其中的 *.o 按源码目录散放，不是独立缓存单元，不能拿来当判据
    sdk = cache / "sdk"
    if sdk.is_dir():
        for d in sorted(sdk.rglob("*")):
            if not d.is_dir():
                continue
            if any(p.is_file() and p.suffix == ".a" for p in d.iterdir()):
                leaves.append((d, "SDK 编译缓存"))

    return leaves


def check_r6(rep: Report) -> None:
    home = user_home()
    cache = home / "cache"
    if not cache.is_dir():
        return

    # ① 派生物叶子目录：指纹文件必须在产物旁边
    for leaf, kind in _derived_leaf_dirs(cache):
        rel = f"~/.firmforge/{leaf.relative_to(home).as_posix()}/"
        if any((leaf / n).is_file() for n in LOCK_NAMES):
            rep.info("R6", rel, f"{kind}带 lock.json")
        elif any((leaf / n).is_file() for n in MANIFEST_NAMES):
            rep.warn("R6", rel,
                     f"{kind}的指纹文件叫 manifest.json —— derived 的声明文件"
                     "统一叫 lock.json（manifest 留给 vendor，标准 §5.2）")
        else:
            rep.warn("R6", rel, f"{kind}缺 lock.json，无法判断可否安全丢弃")

    # ② 构建产物：整块可删、重编即恢复，复用键由 .ff-run/state.json 的
    #    四指纹驱动，不按目录逐个写 lock（标准 §5.2 的意图是「丢弃前
    #    能判定是否陈旧」，这里由 state.json 承担）
    build = cache / "build"
    if build.is_dir():
        n = sum(1 for d in build.rglob("*") if d.is_dir()
                and any((d / f).is_file()
                        for f in ("firmware.hex", "firmware.elf")))
        if n:
            rep.info("R6", "~/.firmforge/cache/build/",
                     f"{n} 个构建产物目录：复用由 state.json 四指纹判定，"
                     "整块可删（重编即恢复）")

    # ③ first-party 产物嵌在 vendor 子树内 —— 跨区归属混乱
    pkgs = home / "packages"
    if pkgs.is_dir():
        for build_dir in pkgs.rglob("build"):
            if build_dir.is_dir():
                rep.warn(
                    "R6",
                    f"~/.firmforge/{build_dir.relative_to(home).as_posix()}/",
                    "first-party 产物嵌在 vendor 子树内（标准 §10.3 P2）",
                )


# --------------------------------------------------------------------------
# R7 —— 用户级新增子树必须先登记
# --------------------------------------------------------------------------


def check_r7(rep: Report) -> None:
    home = user_home()
    if not home.is_dir():
        return
    for child in sorted(home.iterdir()):
        if not child.is_dir():
            continue
        if child.name in USER_REGISTERED_SUBTREES:
            rep.info("R7", f"~/.firmforge/{child.name}/", "已登记")
        else:
            rep.warn(
                "R7",
                f"~/.firmforge/{child.name}/",
                "未在标准 §5 登记的用户级子树",
            )


# --------------------------------------------------------------------------
# R8 —— 归属未决定：承诺级目录下既未入库、也未被 .gitignore 覆盖
# --------------------------------------------------------------------------


def git_undecided(root: Path) -> list[str] | None:
    """未入库、且未被 .gitignore 覆盖的文件。

    这类文件的特征不是「违规」，而是**没人做过决定**：它既不是承诺级
    （没入库），也不是被显式排除的派生物／运行时（没进 .gitignore）。
    标准 §7 决策树要求每个文件都有明确归属，所以它必须被处理 ——
    要么 ``git add``，要么进 ``.gitignore``。
    """
    code, out = run_git(["ls-files", "-o", "--exclude-standard", "-z"], root)
    if code != 0:
        return None
    return [p.replace("\\", "/") for p in out.split("\0") if p.strip()]


def check_r8(root: Path, rep: Report) -> None:
    undecided = git_undecided(root)
    if undecided is None:
        rep.warn("R8", "-", "git 不可用，跳过「归属未决定」检查")
        return
    if not undecided:
        rep.info("R8", "项目内", "无归属未决定的文件")
        return
    for rel in sorted(undecided):
        rep.error(
            "R8",
            rel,
            "既未入库、也未被 .gitignore 覆盖 —— 归属未决定，见标准 §7 决策树",
        )


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description="FirmForge 路径分区标准校验")
    ap.add_argument("--json", action="store_true", help="纯 JSON 输出到 stdout")
    ap.add_argument("--strict", action="store_true", help="WARN 也视为失败")
    args = ap.parse_args()

    start = Path.cwd()
    root = find_repo_root(start)
    if root is None:
        print("ERROR: 不在 git 仓库内", file=sys.stderr)
        return 2

    tracked = git_tracked(root)
    rep = Report()

    check_r1(root, tracked, rep)
    check_r2(root, tracked, rep)
    check_r3(rep)
    check_r4(root, rep)
    check_r5(root, rep)
    check_r6(rep)
    check_r7(rep)
    check_r8(root, rep)

    summary = {
        "repo": str(root),
        "firmforge_home": str(user_home()),
        "tracked_files": len(tracked),
        "errors": len(rep.errors),
        "warnings": len(rep.warnings),
        "infos": len(rep.infos),
    }

    if args.json:
        payload: dict[str, Any] = {
            "ok": rep.ok(),
            "summary": summary,
            "errors": rep.errors,
            "warnings": rep.warnings,
            "infos": rep.infos,
        }
        # JSON 是给机器读的契约：强制 UTF-8 输出，不让编码跟随系统 locale。
        # 中文 Windows 下 stdout 被重定向时默认编成 cp936(GBK)，任何按 UTF-8
        # 消费这份 JSON 的调用方（如 tests/test_layout.py）都会解码崩溃，
        # 且报错表现为「校验器无输出」这种极具误导性的样子。
        # 只改 JSON 分支：人眼查看的文本模式保持原样，控制台渲染不受影响。
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (AttributeError, OSError, ValueError):
            pass
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"仓库: {root}")
        print(f"用户级: {user_home()}   入库文件: {len(tracked)}")
        print("-" * 68)
        for label, items in (
            ("ERROR", rep.errors),
            ("WARN ", rep.warnings),
            ("INFO ", rep.infos),
        ):
            for it in items:
                print(f"[{label}] {it['rule']}  {it['item']}")
                print(f"         {it['detail']}")
        print("-" * 68)
        print(
            f"结果: {len(rep.errors)} error / "
            f"{len(rep.warnings)} warn / {len(rep.infos)} info"
        )

    if not rep.ok():
        return 1
    if args.strict and rep.warnings:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
