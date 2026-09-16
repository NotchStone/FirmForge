"""`avr_registers` 提取器的**纯结构层**测试。

只测第一层（读文本 → 位域归属），不依赖 avr-gcc，因此任何环境都能跑。
第二层（问 avr-gcc）由 `tests/test_knowledge_golden.py` 覆盖。

这一层的三条规则都是踩过坑固化下来的，回归代价高，所以逐条钉住：
  1. ``# define``（``#`` 后有空格）必须识别 —— 否则漏 27 个寄存器
  2. ``#if/#else/#endif`` 必须透明 —— 否则 ADCSRB/PCICR 的位全丢
  3. 连续空行容忍上限 2 —— 否则 SREG 的 8 个位全丢；超过 2 则必须断块
"""

from __future__ import annotations

import pytest

from firmforge.knowledge.extractors import avr_registers as ex


def _attr(*lines: str) -> dict:
    return ex._parse_lines(list(lines))


# --------------------------------------------------------------------------
# 规则 1：缩进预处理指令
# --------------------------------------------------------------------------


def test_indented_hash_define_is_recognised() -> None:
    """共享头里端口 H–L 是 `# define PORTH ...` 写法。"""
    attr = _attr(
        "# define PORTH  _SFR_MEM8(0x102)",
        "# define PH7    7",
        "# define PH0    0",
    )
    assert list(attr) == ["PORTH"]
    assert [(f["name"], f["bit"]) for f in attr["PORTH"]] == [("PH0", 0), ("PH7", 7)]


def test_plain_hash_define_still_works() -> None:
    attr = _attr(
        "#define UCSR0A  _SFR_MEM8(0xC0)",
        "#define RXC0    7",
        "#define MPCM0   0",
    )
    assert [(f["name"], f["bit"]) for f in attr["UCSR0A"]] == [("MPCM0", 0), ("RXC0", 7)]


# --------------------------------------------------------------------------
# 规则 2：条件编译透明
# --------------------------------------------------------------------------


def test_conditional_directives_do_not_break_bit_block() -> None:
    """PCICR 的真实形态：`#if` 夹在位块中间。"""
    attr = _attr(
        "#define PCICR   _SFR_MEM8(0x68)",
        "#if defined(__ATmegaxx0__)",
        "# define PCIE2  2",
        "#endif /* __ATmegaxx0__ */",
        "#define PCIE1   1",
        "#define PCIE0   0",
    )
    assert sorted(f["bit"] for f in attr["PCICR"]) == [0, 1, 2]


# --------------------------------------------------------------------------
# 规则 3：空行容忍上限
# --------------------------------------------------------------------------


def test_two_blank_lines_are_tolerated() -> None:
    """SREG 的真实形态：定义与位块之间隔两个空行。"""
    attr = _attr(
        "#  define SREG _SFR_MEM8(0x3F)",
        "",
        "",
        "/* SREG bit definitions */",
        "#  define SREG_C  (0)",
        "#  define SREG_I  (7)",
    )
    assert sorted(f["bit"] for f in attr["SREG"]) == [0, 7]


def test_three_blank_lines_break_the_block() -> None:
    """超过上限必须断块，否则器件尾部常量会贴到最后一个寄存器上。"""
    attr = _attr(
        "#define UCSR0A  _SFR_MEM8(0xC0)",
        "#define RXC0    7",
        "",
        "",
        "",
        "#define FUSE_MEMORY_SIZE 3",
    )
    assert [f["name"] for f in attr["UCSR0A"]] == ["RXC0"]


def test_parenthesised_bit_form_is_accepted() -> None:
    attr = _attr(
        "#define SREG _SFR_MEM8(0x3F)",
        "#define SREG_C  (0)",
        "#define SREG_Z  (1)",
    )
    assert [(f["name"], f["bit"]) for f in attr["SREG"]] == [
        ("SREG_C", 0), ("SREG_Z", 1)]


# --------------------------------------------------------------------------
# 断块与越界
# --------------------------------------------------------------------------


def test_out_of_range_bit_breaks_block() -> None:
    """`#define SPM_PAGESIZE 256` 不是位域，必须断块。"""
    attr = _attr(
        "#define UCSR0A  _SFR_MEM8(0xC0)",
        "#define RXC0    7",
        "#define SPM_PAGESIZE 256",
        "#define TXC0    6",
    )
    assert [f["name"] for f in attr["UCSR0A"]] == ["RXC0"]


def test_non_numeric_define_breaks_block() -> None:
    attr = _attr(
        "#define UCSR0A  _SFR_MEM8(0xC0)",
        "#define RXC0    7",
        "#define FUSE_CKSEL0      (unsigned char)~_BV(0)",
        "#define TXC0    6",
    )
    assert [f["name"] for f in attr["UCSR0A"]] == ["RXC0"]


def test_new_register_starts_a_new_block() -> None:
    attr = _attr(
        "#define UCSR0A  _SFR_MEM8(0xC0)",
        "#define RXC0    7",
        "#define UCSR0B  _SFR_MEM8(0xC1)",
        "#define RXCIE0  7",
    )
    assert list(attr) == ["UCSR0A", "UCSR0B"]
    assert [f["name"] for f in attr["UCSR0A"]] == ["RXC0"]
    assert [f["name"] for f in attr["UCSR0B"]] == ["RXCIE0"]


def test_duplicate_register_definition_keeps_collecting() -> None:
    """两条条件分支同名定义 —— 归属表按名合并，位块继续挂上去。"""
    attr = _attr(
        "#if __AVR_ARCH__ >= 100",
        "#  define SREG _SFR_MEM8(0x3F)",
        "#else",
        "#  define SREG _SFR_IO8(0x3F)",
        "#endif",
        "#define SREG_C (0)",
    )
    assert list(attr) == ["SREG"]
    assert [(f["name"], f["bit"]) for f in attr["SREG"]] == [("SREG_C", 0)]


def test_field_deduplication_within_block() -> None:
    """同名位域只收一次（SPMCSR 的 SELFPRGEN 与 SPMEN 同为 bit 0）。"""
    attr = _attr(
        "#define SPMCSR _SFR_IO8(0x37)",
        "#define SELFPRGEN 0",
        "#define SPMEN 0",
        "#define PGERS 1",
    )
    fields = [(f["name"], f["bit"]) for f in attr["SPMCSR"]]
    assert fields == [("SELFPRGEN", 0), ("SPMEN", 0), ("PGERS", 1)]


# --------------------------------------------------------------------------
# 器件名推导
# --------------------------------------------------------------------------


@pytest.mark.parametrize("stem,expected", [
    ("iom2560", "atmega2560"),
    ("iom328p", "atmega328p"),
    ("iom88pa", "atmega88pa"),
    ("iotn2313", "attiny2313"),
    ("iomxx0_1", None),      # 家族共享头，不是器件
])
def test_guess_device_name(stem: str, expected: str | None) -> None:
    assert ex.guess_device_name(f"{stem}.h") == expected
