"""``ff context`` 的板卡抽象测试 —— 规格归一 + 主题语义。

守三件事，每一条都对应一次真实故障：

1. **规格字段的读法只有一种。** 三块板卡都把容量/频率写在 ``specs`` 下，
   而实现曾经读 ``mcu.flash_size`` —— 这个字段哪块板卡都没有，于是
   AVR 与 STM32 的 Flash 都显示 0，且不报错。
2. **主题是枚举，不是关键字。** 把 ``--topic registers`` 当成「在寄存器名里
   搜 registers」，最该用的主题永远返回 0 条。
3. **歧义裸名要把候选全列出来。** STM32 上 ``CR1`` 出现在 36 个外设里，
   随便挑一个返回，和返回错值没有区别。
"""

from __future__ import annotations

import pytest

from firmforge.core.board_detector import BoardDetector
from firmforge.core.board_view import (
    board_pin_list,
    board_specs,
    format_freq,
    format_size,
    parse_freq,
    parse_size,
)


# --------------------------------------------------------------------------
# 1. 单位解析
# --------------------------------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("2 MB", 2 * 1024 ** 2),
    ("256 KB", 256 * 1024),
    ("8 KB", 8 * 1024),
    # 括号里是 bootloader 占用说明，不是容量本身
    ("32 KB (0.5 KB bootloader)", 32 * 1024),
    ("1 MB", 1024 ** 2),
    (2097152, 2097152),
    ("2097152", 2097152),
])
def test_parse_size(text, expected):
    assert parse_size(text) == expected


@pytest.mark.parametrize("text, expected", [
    ("480 MHz", 480_000_000),
    ("16 MHz", 16_000_000),
    ("32.768 kHz", 32768),
    (16000000, 16_000_000),
])
def test_parse_freq(text, expected):
    assert parse_freq(text) == expected


@pytest.mark.parametrize("bad", [None, "", "unknown", "-"])
def test_parse_returns_none_when_unparsable(bad):
    """解析不出就返回 None。编一个默认值会把 AVR 的 16 MHz 套到 H743 上。"""
    assert parse_size(bad) is None
    assert parse_freq(bad) is None


def test_format_roundtrip():
    assert format_size(2 * 1024 ** 2) == "2 MB"
    assert format_size(256 * 1024) == "256 KB"
    assert format_size(None) == "unknown"
    assert format_freq(480_000_000) == "480 MHz"
    assert format_freq(16_000_000) == "16 MHz"
    assert format_freq(None) == "unknown"


# --------------------------------------------------------------------------
# 2. 板卡规格归一（读真实 board.yaml）
# --------------------------------------------------------------------------

def _resolve(board_id: str) -> dict:
    config = BoardDetector().resolve_board(board_id)
    assert config, f"board {board_id} not found"
    return config


@pytest.mark.parametrize("board_id, chip, clock, flash, series", [
    ("arduino_mega", "ATmega2560", 16_000_000, 256 * 1024, "avr"),
    ("arduino_328p", "ATmega328P", 16_000_000, 32 * 1024, "avr"),
    ("gc_h743", "STM32H743ZIT6", 480_000_000, 2 * 1024 ** 2, "stm32h7"),
])
def test_board_specs(board_id, chip, clock, flash, series):
    specs = board_specs(_resolve(board_id))
    assert specs["chip"].lower() == chip.lower()
    assert specs["chip_key"] == chip.lower()
    assert specs["clock_hz"] == clock
    assert specs["flash_bytes"] == flash
    assert specs["series"] == series


def test_board_specs_platform_routing():
    """``platform: arduino`` 的寄存器库目录名是 ``avr``，两者不同名。"""
    assert board_specs(_resolve("arduino_mega"))["library"] == "avr"
    assert board_specs(_resolve("gc_h743"))["library"] == "stm32"


def test_board_pin_list_avr_vs_stm32():
    """两套引脚语义不能混：AVR 回答「D13 是哪个端口位」，STM32 回答「LED 接哪儿」。"""
    from firmforge.knowledge.knowledge_base import KnowledgeBase

    mega = _resolve("arduino_mega")
    kb = KnowledgeBase()
    kb.load_for_board(mega)
    fmt, items = board_pin_list(mega, kb.get_pin_map("arduino_mega"))
    assert fmt == "arduino"
    assert len(items) == 70
    assert {"arduino_pin", "port", "bit", "register"} <= set(items[0])

    h743 = _resolve("gc_h743")
    fmt, items = board_pin_list(h743, None)
    assert fmt == "board_declared"
    names = {i["name"] for i in items}
    assert {"led1", "debug_uart", "swd", "ethernet"} <= names


# --------------------------------------------------------------------------
# 3. ff context 端到端（走真实的 A 区 / B 区数据）
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def ctx():
    from firmforge.adapters.commands import do_context
    return do_context


def test_context_stm32_specs(ctx):
    p = ctx("gc_h743")
    assert p["clock_hz"] == 480_000_000
    assert p["flash_bytes"] == 2 * 1024 ** 2
    assert p["ram_bytes"] == 1024 ** 2
    assert p["library"] == "stm32"
    assert p["series"] == "stm32h7"


def test_context_avr_specs(ctx):
    """这条曾经显示 Flash: 0 —— 板卡声明写的是 ``specs.flash: 256 KB``。"""
    p = ctx("arduino_mega")
    assert p["clock_hz"] == 16_000_000
    assert p["flash_bytes"] == 256 * 1024
    assert p["ram_bytes"] == 8 * 1024


def test_context_registers_topic_is_a_mode_not_a_keyword(ctx):
    """``--topic registers`` 是主题。曾经被当成关键字，永远返回 0 条。"""
    import json

    from firmforge.knowledge.extractors.stm32_registers import registers_path

    payload = json.loads(
        registers_path("stm32h743zit6", series="stm32h7")
        .read_text(encoding="utf-8"))

    p = ctx("gc_h743", "registers")
    assert p["topic_mode"] == "registers"
    # 对着产物自己的计数断言，而不是写死 2955/128 —— 那些数字随 CMSIS 头
    # 与 SVD 版本漂移，写死只会让每次重新生成都要改测试，却证明不了
    # 「context 报的数与库里的数一致」这件真正要守的事。
    assert p["register_total"] == payload["_generator"]["counts"]["registers"]
    assert (len(p["register_groups"])
            == payload["_generator"]["counts"]["peripherals"])
    assert p["registers"], "概览至少要给几条样例"


def test_context_registers_include_cmsis_core_block(ctx):
    """内核外设必须在库里 —— 缺了它，诊断/计时类固件的源审查恒定失败。

    `SCB` / `NVIC` / `MPU` / `FPU` 在 SVD 里也有，但寄存器名是 SVD 自己的
    写法（`CFSR_UFSR_BFSR_MMFSR` / `SHCRS`），源码写 `SCB->CFSR` 查不到就
    被判成幻觉寄存器；`DWT` / `CoreDebug` / `SysTick` / `ITM` / `TPI` 则
    整个不在 SVD 里。这条测试盯的是「这些名字查得到」，不是「组数对不对」。
    """
    p = ctx("gc_h743", "registers")
    groups = set(p["register_groups"])
    assert {"SCB", "DWT", "CoreDebug", "SysTick", "ITM", "NVIC"} <= groups

    # (外设, 寄存器, 是否必须有位域)。CYCCNT 是纯计数器，没有位域是正常的。
    for probe, register, want_fields in (
            ("SCB", "CFSR", True),        # 崩溃转储要 SCB_CFSR_IBUSERR 这类宏
            ("SCB", "SHCSR", True),       # SVD 拼成 SHCRS，源码写 SHCSR
            ("DWT", "CYCCNT", False),     # 周期计时只要地址
            ("CoreDebug", "DEMCR", True)):
        q = ctx("gc_h743", f"{probe}.{register}")
        hit = [r for r in q["registers"]
               if r["group"] == probe and r["name"] == register]
        assert hit, f"{probe}.{register} 不在库里 —— 会被判成幻觉寄存器"
        if want_fields:
            assert hit[0].get("fields"), f"{probe}.{register} 没有位域"

    # SVD 的写法不该再出现（留着等于允许源码写一个编译器不认的寄存器名）
    q = ctx("gc_h743", "SCB.CFSR_UFSR_BFSR_MMFSR")
    assert not q["registers"], "SVD 的 SCB 寄存器名未被 CMSIS 名字替换"


def test_context_peripheral_query(ctx):
    p = ctx("gc_h743", "USART1")
    assert p["topic_mode"] == "query"
    names = {r["name"] for r in p["registers"]}
    assert {"CR1", "BRR", "ISR", "RDR", "TDR"} <= names
    for r in p["registers"]:
        assert r["group"] == "USART1"
    # 外设名查询要把位域带上 —— 这是 S2 审查和 Agent 写代码都要用的
    cr1 = next(r for r in p["registers"] if r["name"] == "CR1")
    assert len(cr1["fields"]) > 0


def test_context_ambiguous_register_lists_all_owners(ctx):
    """``CR1`` 在 36 个外设里出现。挑一个返回等于返回错值。"""
    p = ctx("gc_h743", "CR1")
    assert len(p["registers"]) > 1
    groups = {r["group"] for r in p["registers"]}
    assert len(groups) > 1
    assert None not in groups


def test_context_avr_register_query(ctx):
    p = ctx("arduino_mega", "PORTB")
    assert len(p["registers"]) == 1
    assert p["registers"][0]["address"] == "0x25"
    assert p["registers"][0]["size"] == 8


def test_context_pins_topic(ctx):
    p = ctx("arduino_mega", "pins")
    assert p["pins"]["format"] == "arduino"
    assert p["pins"]["count"] == 70
    assert p["registers"] == [], "pins 主题不该顺带返回寄存器"


def test_context_baud_topic(ctx):
    p = ctx("arduino_mega", "baud")
    assert "115200" in p["baud"]
    assert p["baud"]["115200"]["ubrr"] == 8


def test_context_baud_on_stm32_explains_absence(ctx):
    """STM32 没有波特率预设表 —— 说清原因，而不是回一张空表。"""
    p = ctx("gc_h743", "baud")
    assert not p.get("baud")
    assert "PCLK" in p["baud_note"]


def test_context_unknown_topic_is_empty_not_error(ctx):
    p = ctx("arduino_mega", "zzz")
    assert "error" not in p
    assert p["registers"] == []


def test_context_reports_origin(ctx):
    """数据来自 A 区还是 B 区要能看见 —— 分区方案本身看不出来。"""
    p = ctx("gc_h743")
    assert p["origin"]["registers"]["zone"] == "B"
    p = ctx("arduino_mega")
    assert p["origin"]["registers"]["zone"] == "A"


def test_context_unknown_board(ctx):
    p = ctx("no_such_board")
    assert "error" in p
