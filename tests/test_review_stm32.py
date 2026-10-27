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


def test_unknown_peripheral_on_arrow_is_reported(h743):
    """``GPIOZ->BSRR``：外设名写错不能静默。

    实测 2026-10-27 在线验证时发现：``periph not in peripherals`` 直接
    ``continue``，连 ``registers_checked`` 都不加 —— 源码里明明引用了一个
    不存在的外设，审查报告却是「0 处检查、PASS」，等于把线索吞掉。
    ``['BSRR']`` 在库里属于 GPIOA，这个组合几乎只可能是外设名写错。

    只报 warning 不阻断：``GPIOZ`` 未声明，gcc 必然拒 —— 编译才是这类错
    的守门员，S2 只负责把线索交出来。
    """
    _cfg, rv = h743
    res = _review(rv, "  GPIOZ->BSRR = 1;")
    assert res.passed is True, "不该替编译器下判决"
    assert "GPIOZ.BSRR" in {w.register for w in res.warnings}
    assert res.registers_checked >= 1, "报了就得算进检查数，否则计数又在说谎"
    warn = next(w for w in res.warnings if w.register == "GPIOZ.BSRR")
    assert "GPIOZ" in warn.reason and "BSRR" in warn.reason


def test_unknown_peripheral_warning_is_deduplicated(h743):
    """同一个错写在不同行上只报一次，不然 20 行能把日志淹了。"""
    _cfg, rv = h743
    res = _review(rv,
                  "  GPIOZ->BSRR = 1;\n"
                  "  GPIOZ->BSRR = 2;\n"
                  "  GPIOZ->BSRR = 3;")
    hits = [w for w in res.warnings if w.register == "GPIOZ.BSRR"]
    assert len(hits) == 1


def test_unknown_peripheral_with_dot_stays_silent(h743):
    """``A.B`` 形态保持静默 —— 它更可能是结构体成员链，不是外设。

    外设访问在 CMSIS 里一律走 ``->``；``.`` 出现在 HAL 结构体成员链上
    （``osc.PLL.PLLM``）的概率远高于外设。用 ``.`` 报错会把正常 HAL
    配置代码全部打成可疑。
    """
    _cfg, rv = h743
    res = _review(rv, "  GPIOZ.BSRR = 1;")
    assert res.warnings == []


def test_hal_struct_member_chain_is_not_a_register(h743):
    """``osc.PLL.PLLM = ...`` 是 HAL 结构体成员，不是寄存器赋值。

    实测 ``bsp_init.c`` 上误报 8 条（PLLM/PLLN/PLLP/PLLQ/PLLR/PLLRGE/
    PLLVCOSEL/PLLFRACN，全部是 ``RCC_OscInitTypeDef::PLL`` 的成员），
    把寄存器审查计数污染成 ``2/10`` —— 让人以为有 8 个寄存器没解析出来。
    根因：赋值上下文的 ``\\b`` 在 ``.`` 与 ``P`` 之间成立。
    """
    _cfg, rv = h743
    body = (
        "  RCC_OscInitTypeDef o = {0};\n"
        "  o.PLL.PLLM = 5;\n"
        "  o.PLL.PLLN = 160;\n"
        "  o.PLL.PLLP = 2;\n"
        "  o.PLL.PLLRGE = 1;\n"
        "  o.PLL.PLLVCOSEL = 0;\n"
        "  o.PLL.PLLFRACN = 0;"
    )
    res = _review(rv, body)
    assert res.violations == []
    assert res.warnings == [], "成员名被当寄存器查，噪声会淹没真问题"
    assert res.registers_checked == 0


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


# --------------------------------------------------------------------------
# 6. 「未收录」与「幻觉」必须分开
# --------------------------------------------------------------------------
# 只靠知识库时两者输出**一字不差**：都是 "Peripheral register 'X.Y' not
# found in reference library"。可一个是工具该补库，一个是源码该改名 ——
# 2026-10-27 的误判就出在这里（`TIM2->RCR` 是 gcc 认的真寄存器）。

def test_kb_gap_is_warning_not_error(h743):
    """SVD 未建模、但器件头有的寄存器 → warning，不算失败。

    ``TIM2.RCR`` 是 H743 的重复计数器寄存器（RM0433 §40），SVD 里没有，
    器件头 ``TIM_TypeDef.RCR`` 有 —— 这就是典型的知识库缺口。
    """
    _cfg, rv = h743
    res = _review(rv, "  TIM2->RCR = 0;")
    assert res.passed is True, "知识库缺口不该阻断源码"
    assert res.violations == []
    assert res.kb_gaps == 1
    assert res.warnings and res.warnings[0].kb_gap is True
    assert "器件头" in res.warnings[0].evidence, "必须给出第二判据的出处"


def test_hallucinated_register_still_error(h743):
    """两处都查不到 → 真幻觉，仍然阻断。"""
    _cfg, rv = h743
    res = _review(rv, "  GPIOA->BSRRR = 1;")
    assert res.passed is False
    assert res.kb_gaps == 0
    assert res.violations and "无此成员" in res.violations[0].evidence


def test_kb_gap_and_hallucination_are_distinguishable(h743):
    """两者的 reason / evidence 必须不同 —— 否则调用方还是分不开。"""
    _cfg, rv = h743
    gap = _review(rv, "  TIM2->RCR = 0;").warnings[0]
    hal = _review(rv, "  GPIOA->BSRRR = 1;").violations[0]
    assert gap.reason != hal.reason
    assert gap.kb_gap and not hal.kb_gap


def test_no_device_truth_never_blames_source():
    """没有器件头时不许下 error 结论 —— 不知道就说不知道。"""
    cfg = BoardDetector().resolve_board("gc_h743")
    kb = KnowledgeBase()
    kb.load_for_board(cfg)
    rv = SourceReviewer(kb)          # 故意不注入 DeviceTruth
    res = rv.validate("void f(void){ TIM2->RCR = 0; }", "t.c")
    assert res.cross_checked is False
    assert res.passed is True
    assert res.violations == []
    assert res.warnings, "不判对错，但仍要把线索交出来"


# --------------------------------------------------------------------------
# 7. 驼峰实例名：SysTick / CoreDebug
# --------------------------------------------------------------------------
# 实例名正则曾写成 `[A-Z][A-Z0-9]{1,15}`，只认全大写。CMSIS 十个内核组里
# SysTick 与 CoreDebug 是驼峰，于是 `SysTick->LOAD` 一个字都匹配不上 ——
# 知识库明明有，审查完全空转，连 warning 都没有。

def test_systick_is_reviewed(h743):
    _cfg, rv = h743
    res = _review(rv, "  SysTick->LOAD = 1000;\n  SysTick->VAL = 0;")
    assert res.registers_checked == 2, "驼峰实例名必须被扫到"
    assert res.registers_resolved == 2
    assert res.violations == []


def test_coredebug_is_reviewed(h743):
    _cfg, rv = h743
    res = _review(rv, "  CoreDebug->DHCSR = 1;")
    assert res.registers_checked == 1
    assert res.registers_resolved == 1


def test_camelcase_hallucination_caught(h743):
    """驼峰实例名下的错误寄存器同样要抓 —— 放开正则不是为了放过。"""
    _cfg, rv = h743
    res = _review(rv, "  SysTick->LOADX = 1;")
    assert res.registers_checked == 1
    assert res.passed is False


def test_struct_member_chain_not_treated_as_peripheral(h743):
    """`osc.PLL.PLLM` 是 HAL 结构体成员链，不是外设访问。"""
    _cfg, rv = h743
    res = _review(rv, "  osc.PLL.PLLM = 8;\n  huart1.Instance = USART1;")
    assert res.registers_checked == 0, "小写 + 点 应整体跳过"


# --------------------------------------------------------------------------
# 8. 汇总日志必须带落点
# --------------------------------------------------------------------------

def test_fail_log_carries_file_and_line(h743, caplog):
    _cfg, rv = h743
    with caplog.at_level("WARNING", logger="firmforge.core.source_reviewer"):
        rv.validate("void f(void){\n  GPIOA->BSRRR = 1;\n}", "app/bsp.c")
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "app/bsp.c:2" in text, f"汇总日志没有落点，读的人无从下手：{text}"
    assert "GPIOA.BSRRR" in text
