"""项目级审查豁免表 —— 「这几处我核对过，别算了」。

设计取舍（三条都有对应测试）：

1. 理由必填 —— 豁免是承诺，不带理由的承诺等于「别管我」
2. 仍然原样打印 —— 从 violations 移到 allowed，但不隐藏
3. 只按符号精确匹配 —— 通配会让一张表悄悄覆盖一批新出现的名字
"""

from __future__ import annotations

import pytest

from firmforge.core.board_detector import BoardDetector
from firmforge.core.review_allowlist import (
    ALLOWLIST_FILENAME,
    ReviewAllowlist,
)
from firmforge.core.source_reviewer import SourceReviewer
from firmforge.knowledge.knowledge_base import KnowledgeBase


def _write(tmp_path, text):
    p = tmp_path / ALLOWLIST_FILENAME
    p.write_text(text, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# 加载
# ---------------------------------------------------------------------------

def test_missing_file_is_empty_not_error(tmp_path):
    table = ReviewAllowlist.load(tmp_path)
    assert not table
    assert table.problems == []


def test_loads_rules(tmp_path):
    _write(tmp_path, """
allow:
  - symbol: "SCB.CFSR"
    reason: "CMSIS 内核块，对照 core_cm7.h"
  - symbol: "IWDG1.PR"
    file: bsp_init.c
    reason: "库按 SVD 命名为 IWDG"
""")
    table = ReviewAllowlist.load(tmp_path)
    assert len(table) == 2
    assert table.rules[0].symbol == "SCB.CFSR"
    assert table.rules[1].file == "bsp_init.c"


def test_missing_reason_is_reported_not_silent(tmp_path):
    """空理由 = 无效条目，必须报警，不能悄悄生效。"""
    _write(tmp_path, """
allow:
  - symbol: "GPIOA.BSRR"
""")
    table = ReviewAllowlist.load(tmp_path)
    assert len(table) == 0, "没写理由就不该生效"
    assert table.problems
    assert "reason" in table.problems[0]


def test_bad_yaml_reports_problem(tmp_path):
    _write(tmp_path, "allow: [unclosed\n")
    table = ReviewAllowlist.load(tmp_path)
    assert not table
    assert table.problems


def test_no_allow_section_reports_problem(tmp_path):
    _write(tmp_path, "other: 1\n")
    table = ReviewAllowlist.load(tmp_path)
    assert table.problems


# ---------------------------------------------------------------------------
# 匹配
# ---------------------------------------------------------------------------

def test_symbol_match_is_case_insensitive(tmp_path):
    _write(tmp_path, "allow:\n  - symbol: \"scb.cfsr\"\n    reason: \"r\"\n")
    table = ReviewAllowlist.load(tmp_path)
    assert table.match("SCB.CFSR") is not None


def test_no_prefix_or_wildcard_match(tmp_path):
    """`GPIO*` 这种不该命中 —— 豁免是「这一处」而不是「这一类」。"""
    _write(tmp_path, "allow:\n  - symbol: \"GPIO*\"\n    reason: \"r\"\n")
    table = ReviewAllowlist.load(tmp_path)
    assert table.match("GPIOA.BSRR") is None


def test_file_scoped_rule(tmp_path):
    _write(tmp_path, """
allow:
  - symbol: "TIM2.RCR"
    file: bsp_init.c
    reason: "已核对"
""")
    table = ReviewAllowlist.load(tmp_path)
    assert table.match("TIM2.RCR", "/proj/app/bsp_init.c") is not None
    assert table.match("TIM2.RCR", "/proj/app/main.c") is None


def test_global_rule_matches_any_file(tmp_path):
    _write(tmp_path, "allow:\n  - symbol: \"TIM2.RCR\"\n    reason: \"r\"\n")
    table = ReviewAllowlist.load(tmp_path)
    assert table.match("TIM2.RCR", "/proj/app/main.c") is not None


# ---------------------------------------------------------------------------
# 接入审查器
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def h743_cfg():
    cfg = BoardDetector().resolve_board("gc_h743")
    assert cfg
    return cfg


def _reviewer(cfg, allowlist=None):
    kb = KnowledgeBase()
    kb.load_for_board(cfg)
    from firmforge.knowledge.device_truth import DeviceTruth
    return SourceReviewer(kb, device_truth=DeviceTruth.load("stm32h743zit6"),
                          allowlist=allowlist)


def test_allowlisted_violation_no_longer_fails(h743_cfg, tmp_path):
    """豁免后不计惩罚，但**仍然列出来**并带理由。"""
    _write(tmp_path, """
allow:
  - symbol: "GPIOA.BOGUS"
    reason: "这是 BSP 里刻意留的写保护探针，已核对"
""")
    table = ReviewAllowlist.load(tmp_path)
    rv = _reviewer(h743_cfg, table)
    res = rv.validate("void f(void){ GPIOA->BOGUS = 1; }", "bsp.c")

    assert res.passed is True, "声明过豁免的条目不该阻断"
    assert res.violations == []
    assert len(res.allowed) == 1
    assert "写保护探针" in res.allowed[0].allowed_reason
    assert "[ALLOWED]" in str(res.allowed[0])
    # 豁免的寄存器从置信度分母里剔除 —— 否则"豁免"只是不阻断、
    # 分数照样被打到 0%，等于没豁免。
    assert res.registers_allowed == 1


def test_non_allowlisted_still_fails(h743_cfg, tmp_path):
    _write(tmp_path, """
allow:
  - symbol: "GPIOA.BOGUS"
    reason: "r"
""")
    table = ReviewAllowlist.load(tmp_path)
    rv = _reviewer(h743_cfg, table)
    res = rv.validate("void f(void){ GPIOA->NOPE = 1; }", "bsp.c")
    assert res.passed is False, "没声明的照旧阻断"


def test_allowlist_does_not_hide_from_summary(h743_cfg, tmp_path):
    """summary 里要能看到「已豁免 N 条」—— 看不见的豁免等于掩盖。"""
    _write(tmp_path, "allow:\n  - symbol: \"GPIOA.BOGUS\"\n    reason: \"r\"\n")
    table = ReviewAllowlist.load(tmp_path)
    rv = _reviewer(h743_cfg, table)
    res = rv.validate("void f(void){ GPIOA->BOGUS = 1; }", "bsp.c")
    assert "Allowed by project: 1" in res.summary()
