"""分区标准校验测试（依据 docs/路径分区标准.md §6 R1–R7）。

把 ``scripts/check_layout.py`` 接入测试，使新增违规立即可见。

采用 **基线冻结** 策略（而非零容忍）：
- 存量违规不阻塞开发（标准 §9.1 宽容过渡）
- 但**新增**违规会使本测试失败
- 第二步整改（标准 §9.2）完成后，应把 ``BASELINE_ERROR_KEYS`` 清空
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CHECKER = REPO_ROOT / "scripts" / "check_layout.py"

# --------------------------------------------------------------------------
# 存量违规基线
#
# 2026-09-16 第二步整改完成后已**清空** —— 仓库现在零 ERROR。
# 清空是有意的：留下已修复的键会让基线腐烂成永久的免罪符，而
# ``test_baseline_is_tight`` 正是守着这一点。
#
# 若日后确有需要宽容的历史包袱，往这里加键时必须附上原因与整改期限。
# --------------------------------------------------------------------------
BASELINE_ERROR_KEYS: set[str] = set()

# 例外条款上限（标准 §3.1 ①）：小体积派生物方可入库
DERIVED_EXCEPTION_MAX_BYTES = 512 * 1024
DERIVED_EXCEPTION_DIR = REPO_ROOT / "firmforge" / "data" / "knowledge" / "reference"


@pytest.fixture(scope="module")
def report() -> dict:
    """运行校验器并返回其 JSON 报告。"""
    proc = subprocess.run(
        [sys.executable, str(CHECKER), "--json"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert proc.stdout.strip(), f"校验器无输出；stderr={proc.stderr}"
    return json.loads(proc.stdout)


def _keys(items: list[dict]) -> set[str]:
    return {f"{it['rule']}:{it['item']}" for it in items}


# --------------------------------------------------------------------------
# 接口契约
# --------------------------------------------------------------------------


def test_checker_is_executable() -> None:
    assert CHECKER.is_file(), f"缺少校验器 {CHECKER}"


def test_report_schema(report: dict) -> None:
    for key in ("ok", "summary", "errors", "warnings", "infos"):
        assert key in report, f"报告缺少字段 {key}"
    assert isinstance(report["errors"], list)
    assert isinstance(report["warnings"], list)
    assert report["summary"]["tracked_files"] > 0


def test_exit_code_consistent(report: dict) -> None:
    """有 ERROR 时退出码必须非 0，否则 CI 无法把关。"""
    proc = subprocess.run(
        [sys.executable, str(CHECKER)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if report["errors"]:
        assert proc.returncode == 1
    else:
        assert proc.returncode == 0


# --------------------------------------------------------------------------
# 规则校验
# --------------------------------------------------------------------------


def test_no_new_errors(report: dict) -> None:
    """不得引入基线之外的 ERROR（标准 R1–R7）。"""
    new = _keys(report["errors"]) - BASELINE_ERROR_KEYS
    assert not new, (
        "检测到分区标准新增违规：\n  "
        + "\n  ".join(sorted(new))
        + "\n请查阅 docs/路径分区标准.md §5 归属矩阵修正。"
    )


def test_baseline_is_tight(report: dict) -> None:
    """基线不得包含已修复项 —— 防止基线腐烂成免罪符。"""
    stale = BASELINE_ERROR_KEYS - _keys(report["errors"])
    assert not stale, (
        "基线中存在已不存在的违规，请从 BASELINE_ERROR_KEYS 移除：\n  "
        + "\n  ".join(sorted(stale))
    )


def test_derived_not_tracked(report: dict) -> None:
    """R2：派生物不得入库（例外条款除外）。"""
    violations = [e for e in report["errors"] if e["rule"] == "R2"]
    assert not violations, f"派生物入库：{violations}"


def test_exception_clause_within_limit() -> None:
    """R2 例外条款：小体积派生物目录不得超过上限。"""
    if not DERIVED_EXCEPTION_DIR.is_dir():
        pytest.skip("例外条款目录不存在")
    total = sum(
        p.stat().st_size
        for p in DERIVED_EXCEPTION_DIR.rglob("*")
        if p.is_file()
    )
    assert total <= DERIVED_EXCEPTION_MAX_BYTES, (
        f"{DERIVED_EXCEPTION_DIR.relative_to(REPO_ROOT)} 累计 {total} B，"
        f"超过例外条款上限 {DERIVED_EXCEPTION_MAX_BYTES} B；"
        "超出后应从 A 区迁往 B 区（标准 §3.1 ①）。"
    )


def test_no_name_collision(report: dict) -> None:
    """R4 / N1：项目内目录不得与用户级根目录同名。"""
    # 当前基线内已知此违规，故只断言「没有第二个」
    collisions = [e for e in report["errors"] if e["rule"] == "R4"]
    assert len(collisions) <= 1, f"出现多处同名冲突：{collisions}"


def test_vendor_manifests_declared(report: dict) -> None:
    """R3：vendor 子树应带 manifest（缺失为 WARN，此处仅统计）。"""
    missing = [w for w in report["warnings"] if w["rule"] == "R3"]
    # 机制待补齐，不阻断；但数量不应失控
    assert len(missing) <= 5, f"缺 manifest 的 vendor 子树过多：{missing}"
