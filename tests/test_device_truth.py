"""器件头判据层 —— 「未收录」与「幻觉」的分界线。

背景：知识库按 SVD 生成，SVD 未建模的寄存器（H743 实测约 100 条）查不到，
幻觉寄存器也查不到。只靠知识库时两者输出**一字不差**，工具在「不知道」的
时候用了「你错了」的语气。

本层的每一条断言都对应一个真实误判场景，不是形式化覆盖：

- ``TIM2.RCR``：真寄存器、SVD 未建模 → 必须 PRESENT（未收录）
- ``GPIOA.BOGUS``：幻觉 → 必须 ABSENT
- ``SysTick.LOAD``：内核块，只定义在 ``core_cm7.h``，器件头里**一个都查不到**
- ``DMA1_Stream0``：SVD 拍平成 ``DMA1.S0CR``，实物是独立的 8 个实例 →
  两套头都查不到，只能 NO_INSTANCE，不许瞎判
"""

from __future__ import annotations

import pytest

from firmforge.knowledge.device_truth import DeviceTruth, Verdict, clear_cache

pytestmark = pytest.mark.skipif(
    DeviceTruth.load("stm32h743zit6").available is False,
    reason="本机未安装 CMSIS 器件头（ff setup 可装）",
)


@pytest.fixture(scope="module")
def h743():
    clear_cache()
    return DeviceTruth.load("stm32h743zit6")


# ---------------------------------------------------------------------------
# 可用性与降级
# ---------------------------------------------------------------------------

def test_avr_chip_has_no_device_truth():
    """AVR 没有 CMSIS 器件头 —— 本层不可用，审查退化为「不知道」。"""
    truth = DeviceTruth.load("atmega2560")
    assert truth.available is False
    assert truth.check("PORTB", "DDRB") == Verdict.UNAVAILABLE


def test_unknown_chip_does_not_raise():
    assert DeviceTruth.load("").available is False
    assert DeviceTruth.load("no_such_mcu").available is False


# ---------------------------------------------------------------------------
# 外设：器件头
# ---------------------------------------------------------------------------

def test_real_register_is_present(h743):
    assert h743.check("GPIOA", "BSRR") == Verdict.PRESENT
    assert h743.struct_of("GPIOA") == "GPIO_TypeDef"


def test_hallucinated_register_is_absent(h743):
    assert h743.check("GPIOA", "BOGUS") == Verdict.ABSENT
    assert h743.check("GPIOA", "BSRRR") == Verdict.ABSENT


def test_svd_gap_is_present(h743):
    """`TIM2.RCR` 在器件头里，SVD 里没有 —— 这是「未收录」，不是幻觉。"""
    assert h743.check("TIM2", "RCR") == Verdict.PRESENT


def test_unknown_instance_is_not_judged(h743):
    """实例名对不上就不下结论。

    ``DMA1_Stream0`` 是特例：器件头**有**独立的 Stream 实例宏，所以它能被
    认出来（→ PRESENT），而知识库按 SVD 拍平成 ``DMA1.S0CR`` 收录。
    真正的 NO_INSTANCE 是那种哪儿都没有的名字。
    """
    assert h743.check("GPIOZ", "BSRR") == Verdict.NO_INSTANCE
    assert h743.check("HAL_GPIO_WritePin", "BSRR") == Verdict.NO_INSTANCE


def test_dma_stream_instance_is_known(h743):
    """`DMA1_Stream0` 在器件头里有指针宏 —— 不该退回「不知道」。"""
    assert h743.check("DMA1_Stream0", "CR") == Verdict.PRESENT


# ---------------------------------------------------------------------------
# 内核块：只定义在 CMSIS Core 头
# ---------------------------------------------------------------------------

def test_systick_comes_from_core_header(h743):
    """SysTick 在 stm32h743xx.h 里一个都没有，只在 core_cm7.h。"""
    assert h743.check("SysTick", "LOAD") == Verdict.PRESENT
    assert h743.check("SysTick", "VAL") == Verdict.PRESENT
    assert h743.check("SysTick", "LOADX") == Verdict.ABSENT


def test_coredebug_comes_from_core_header(h743):
    assert h743.check("CoreDebug", "DHCSR") == Verdict.PRESENT
    assert h743.check("CoreDebug", "DEMCR") == Verdict.PRESENT
    assert h743.check("CoreDebug", "NOSUCH") == Verdict.ABSENT


def test_instance_lookup_is_case_insensitive(h743):
    """源码审查传的是 `.upper()` 的名字，core 头里是驼峰。"""
    assert h743.check("SYSTICK", "LOAD") == h743.check("SysTick", "LOAD")
    assert h743.struct_of("SYSTICK") == h743.struct_of("SysTick")


def test_source_names_both_headers(h743):
    """证据出处必须写清是哪个头 —— 否则「器件头有」无法复核。"""
    assert "stm32h743xx.h" in h743.source
    assert "core_cm7.h" in h743.source


# ---------------------------------------------------------------------------
# 覆盖规模（回归：合并 core 头不能把器件头挤掉）
# ---------------------------------------------------------------------------

def test_both_headers_are_merged(h743):
    assert h743.instance_count > 242, "core 头应当新增实例"
    assert h743.struct_count > 77, "core 头应当新增结构体"
