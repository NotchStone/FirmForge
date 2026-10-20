"""S2 对 STM32 源码的寄存器审查 —— 限定名、位宏、别名。

修之前，STM32 的引用**一条都没被真正审查过**：

- ``USART1->CR1`` 里的裸名 ``CR1`` 落到 Phase 2，而裸名在 STM32 上跨 36 个
  外设重名，``lookup_register("CR1")`` 返回其中随便一个 —— 报告显示
  「已解析」，实际解析到了别的外设。
- ``USART1->CRX``（不存在的寄存器）只产生一条 warning，不阻断：AVR 的
  寄存器前缀表（``PORT`` / ``UCSR`` / ``ADC`` …）里没有 STM32 的名字。
- ``GPIO_MODER_BOGUS``（打错的位宏）完全没被看到 —— 它不在
  ``(1 << X)`` / ``_BV(X)`` 形态里。

三条修法各有对应的测试，最后一条守住「不许为了抓错而误伤 HAL 常量」。
"""

from __future__ import annotations

import pytest

from firmforge.core.board_detector import BoardDetector
from firmforge.core.source_reviewer import SourceReviewer
from firmforge.knowledge.knowledge_base import KnowledgeBase


@pytest.fixture(scope="module")
def h743():
    cfg = BoardDetector().resolve_board("gc_h743")
    assert cfg, "gc_h743 板卡定义缺失"
    kb = KnowledgeBase()
    return cfg, SourceReviewer.for_board(kb, board=cfg)


@pytest.fixture(scope="module")
def mega():
    cfg = BoardDetector().resolve_board("arduino_mega")
    assert cfg
    kb = KnowledgeBase()
    return cfg, SourceReviewer.for_board(kb, board=cfg)


def _names(result) -> set[str]:
    return {v.register.upper() for v in result.violations}


def _review(reviewer, body: str):
    return reviewer.validate("void f(void) {\n" + body + "\n}\n", "t.c")


# --------------------------------------------------------------------------
# 1. 外设寄存器：按限定名查
# --------------------------------------------------------------------------

def test_valid_peripheral_register_resolves(h743):
    _cfg, rv = h743
    res = _review(rv, "  USART1->CR1 |= USART_CR1_TE;")
    assert res.violations == []
    assert res.registers_resolved == res.registers_checked
    assert res.registers_checked >= 1


def test_unknown_register_on_known_peripheral_is_error(h743):
    """``USART1`` 存在、``CRX`` 不存在 —— 这是真错，不是「没查到」。"""
    _cfg, rv = h743
    res = _review(rv, "  USART1->CRX = 1;")
    assert res.passed is False
    assert "USART1.CRX" in _names(res)
    assert res.violations[0].severity == "error"


def test_bare_name_on_peripheral_is_not_rechecked(h743):
    """``CR1`` 被 Phase 0 按限定名判定后，不该再当裸名查一遍。

    再查一遍只会「查到」某个外设的同名寄存器，把真错洗成假通过。
    """
    _cfg, rv = h743
    res = _review(rv, "  USART1->CRX = 1;")
    assert "CRX" not in _names(res), "裸名路径不该再报一次同一个标识符"


def test_dot_form_is_recognised(h743):
    """``PERIPH.REG`` 与 ``PERIPH->REG`` 同等对待（HAL 内部有这种写法）。"""
    _cfg, rv = h743
    res = _review(rv, "  GPIOA.MODER = 0;")
    assert res.violations == []
    assert res.registers_checked >= 1


# --------------------------------------------------------------------------
# 2. 位宏：全名命中 / 前缀命中 / 两者都不命中
# --------------------------------------------------------------------------

def test_known_field_macro_resolves(h743):
    _cfg, rv = h743
    res = _review(rv, "  GPIOA->MODER = GPIO_MODER_MODER0;")
    assert res.violations == []
    assert res.fields_resolved >= 1


def test_misspelled_field_macro_is_error(h743):
    """前缀 ``GPIO_MODER_`` 下有一批真位 —— 说明寄存器对了、位名错了。"""
    _cfg, rv = h743
    res = _review(rv, "  GPIOA->MODER = GPIO_MODER_BOGUS;")
    assert res.passed is False
    assert "GPIO_MODER_BOGUS" in _names(res)


def test_hal_constants_are_not_flagged(h743):
    """``GPIO_PIN_7`` 是 HAL 常量，寄存器库里没有它是正常的。

    判据是「前缀下有没有已知位」。``GPIO_PIN_`` 这一族在寄存器数据里
    不存在，所以不能因为查不到就报错 —— 否则每个 HAL 工程都会刷屏。
    """
    _cfg, rv = h743
    res = _review(rv, "  HAL_GPIO_WritePin(GPIOA, GPIO_PIN_7, 1);")
    assert res.violations == []
    assert res.passed is True


def test_unknown_prefix_without_family_is_ignored(h743):
    """``USART_CR9_TE``：``USART_CR9_`` 这一族根本不存在，无法判定。

    判不了就放过 —— 编译器会拦 undefined identifier，S2 不该猜。
    """
    _cfg, rv = h743
    res = _review(rv, "  x = USART_CR9_TE;")
    assert res.violations == []


# --------------------------------------------------------------------------
# 3. 真实源码零误报
# --------------------------------------------------------------------------

def test_real_hal_source_has_no_false_positive(h743):
    _cfg, rv = h743
    from pathlib import Path
    src = Path("firmforge/data/boards/gc_h743/apps/hello_blink/main.c")
    if not src.exists():
        pytest.skip("hello_blink 源文件缺失")
    res = rv.validate(src.read_text(encoding="utf-8"), "main.c")
    assert res.passed is True, [f"{v.register}: {v.reason}" for v in res.violations]
    assert res.warnings == []


# --------------------------------------------------------------------------
# 4. AVR 路线不受影响
# --------------------------------------------------------------------------

def test_avr_register_still_reviewed(mega):
    _cfg, rv = mega
    res = _review(rv, "  PORTB = 0xFF;")
    assert res.violations == []
    assert res.registers_resolved >= 1


def test_avr_hallucinated_register_still_error(mega):
    _cfg, rv = mega
    res = _review(rv, "  PORTZ = 0xFF;")
    assert res.passed is False


# --------------------------------------------------------------------------
# 5. 索引本身
# --------------------------------------------------------------------------

def test_field_index_covers_cmsis_macros(h743):
    _cfg, rv = h743
    kb = rv.knowledge_base
    assert kb.stats()["total_field_names_indexed"] > 5000
    assert kb.lookup_field("USART_CR1_TE") is not None
    assert kb.lookup_field("GPIO_MODER_MODER0") is not None
    assert kb.lookup_field("NO_SUCH_FIELD_XYZ") is None


def test_field_prefix_boundary():
    """前缀判定不能太宽松，也不能太严：``GPIO_PIN_7`` 必须放过。"""
    cfg = BoardDetector().resolve_board("gc_h743")
    kb = KnowledgeBase()
    kb.load_for_board(cfg)
    assert kb.field_prefix_of("GPIO_MODER_BOGUS") == "GPIO_MODER_"
    assert kb.field_prefix_of("GPIO_PIN_7") is None
    assert kb.field_prefix_of("HAL_UART_Transmit") is None
