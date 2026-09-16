"""生成器 ↔ 金标准 一致性测试（`firmforge/knowledge/parity.py`）。

三层断言，严重程度不同：

1. **覆盖性（硬）**：金标准里的每个寄存器、每个位，生成器都必须认得。
   缺失 = 生成器对硬件瞎了，直接失败。当前 **零缺失**。
2. **值一致性（硬）**：同名寄存器/位域值不同、或位名在器件头里查无此名
   —— 必有一方错。冻结表现在**是空的**（2026-09-16 修正了 40 处已核实
   错误），机制保留：新增差异即失败，修一处就删一条。
3. **一致性口径（硬）**：`conditional_filter` 必须真生效，否则生成器
   在给家族共享头出数据时会混进别的型号。

比对需要 avr-gcc（第二层解析用它求值条件编译）。未装工具链则跳过 ——
但跳过意味着这条防线当次不生效，所以 CI 里应当有工具链。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from firmforge.knowledge import parity

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def reports() -> list[parity.McuParity]:
    from firmforge.knowledge.extractors import avr_registers as ex

    include_dir = ex.default_avr_include_dir()
    if not include_dir.is_dir():
        pytest.skip(f"avr-libc 器件头目录不存在：{include_dir}")
    from firmforge.providers.arduino.toolchain import find_avr_gcc
    if not find_avr_gcc()[0]:
        pytest.skip("未找到 avr-gcc，无法做两层解析")
    return parity.compare_all(REPO_ROOT, include_dir)


def _by_mcu(reports: list[parity.McuParity]) -> dict[str, parity.McuParity]:
    return {r.mcu: r for r in reports}


# --------------------------------------------------------------------------
# 1. 覆盖性 —— 硬断言
# --------------------------------------------------------------------------


def test_generator_covers_every_golden_register(
        reports: list[parity.McuParity]) -> None:
    for rep in reports:
        assert not rep.registers_missing, (
            f"{rep.mcu}: 生成器漏掉金标准里的寄存器 {rep.registers_missing}；"
            "说明器件头解析有盲区。"
        )


def test_generator_covers_every_golden_bit(
        reports: list[parity.McuParity]) -> None:
    """金标准记录的每一位，生成器都要知道其存在。

    例外见 `KNOWN_GOLDEN_ONLY_BITS`。
    """
    for rep in reports:
        unexpected = [b for b in rep.bits_missing
                      if b not in KNOWN_GOLDEN_ONLY_BITS.get(rep.mcu, set())]
        assert not unexpected, (
            f"{rep.mcu}: 生成器漏掉金标准里的位 {unexpected}；"
            "若确认 avr-libc 未定义该位，登记到 KNOWN_GOLDEN_ONLY_BITS 并说明。"
        )


def test_reported_bit_gaps_are_still_missing(
        reports: list[parity.McuParity]) -> None:
    """已登记的缺口不得「悄悄没了」—— 修好后必须把条目删掉。"""
    for rep in reports:
        stale = set(KNOWN_GOLDEN_ONLY_BITS.get(rep.mcu, set())) - set(rep.bits_missing)
        assert not stale, (
            f"{rep.mcu}: 下列缺口已不存在，请从 KNOWN_GOLDEN_ONLY_BITS 移除："
            f"{sorted(stale)}"
        )


# --------------------------------------------------------------------------
# 2. 值一致性 —— 冻结（当前已清空：差异全部修正）
# --------------------------------------------------------------------------
#
# 2026-09-16：金标准中的 40 处已核实错误**已按器件头修正**，三张冻结表
# 因此清空。清空不是把它们删掉 —— 机制保留，一旦再出现
# 差异就立即失败。修正依据（按权威性排序）：
#
#   ① avr-libc 器件头 —— 编译器实际使用的定义。本机三份**独立分发**的副本
#      逐字节一致：Atmel 7.3.0 / Arduino IDE 1.8.57 / avr-gcc 14.1.0。
#   ② 厂商数据手册 —— Atmel 2549（ATmega640/1280/1281/2560/2561）与
#      Microchip DS40002061B（ATmega328P）的 Register Summary，与①逐字吻合。
#   ③ alldatasheet 扫描件（辅助佐证）。
#
# 修正清单（详见两个数据文件的顶层 `_revision` 字段）：
#
#   2560：端口 H–L 地址 12 条 0x35..0x43 → 0x100..0x10B（原值像是把 I/O
#         空间的空闲地址当成了端口）；EEAR 0x21 → 0x41（口径混用：全表是
#         内存地址，唯独它写了 I/O 地址）；ASSR 位号 6 条整体错位；
#         UCSR0B/1B/2B/3B 位名 8 条 TXBx8 → TXB8x（字符转置，而 328p 那份
#         写的是对的 —— 同批生成的不一致本身就是证据）；
#         顶层 source 的 DS40002591B **查无此号** → 改为已核实的 Atmel 2549。
#   328p：EEAR 同左；ASSR 位号同左；MCUCR.BODSE 7 → 5；
#         UBRR0H.URSEL0 删除 —— ATmega328P 的 UBRR0H 只有 bit3:0。
#
# 判据：器件头是**运行时真相**（代码最终要被 avr-gcc 编译、被硬件执行），
# 手册是它的书面依据；两者冲突时以器件头为准并留痕。金标准不是"另一种
# 合法口径"—— 它就是错。

#: 金标准有、avr-libc 不定义该位的条目。（当前为空）
KNOWN_GOLDEN_ONLY_BITS: dict[str, set[tuple[str, int]]] = {
    "atmega2560": set(),
    "atmega328p": set(),
}

#: 同名寄存器地址不一致：{mcu: {寄存器: (金标准, 器件头)}}。（当前为空）
KNOWN_ADDRESS_DISCREPANCIES: dict[str, dict[str, tuple[str, str]]] = {
    "atmega2560": {},
    "atmega328p": {},
}

#: 同名位域位号不一致：{mcu: {寄存器.位域: (金标准, 器件头)}}。（当前为空）
KNOWN_BIT_DISCREPANCIES: dict[str, dict[str, tuple[int, int]]] = {
    "atmega2560": {},
    "atmega328p": {},
}

#: 金标准位名在器件头里查无此名：{mcu: {寄存器.位名}}。（当前为空）
#:
#: 位号对、位名错最阴：编译器只认宏名，写 `(1 << TXB08)` 编不过，而按位号
#: 比对永远发现不了。命名口径差异（`C` vs `SREG_C`）由 `parity._field_known`
#: 的第二段规则消化，不进这张表。
KNOWN_UNKNOWN_BIT_NAMES: dict[str, set[str]] = {
    "atmega2560": set(),
    "atmega328p": set(),
}


def test_no_new_address_discrepancies(
        reports: list[parity.McuParity]) -> None:
    for rep in reports:
        expected = KNOWN_ADDRESS_DISCREPANCIES.get(rep.mcu, {})
        assert rep.address_mismatch == expected, (
            f"{rep.mcu}: 地址差异与冻结清单不符。\n"
            f"  新增/变化: "
            f"{ {k: v for k, v in rep.address_mismatch.items() if expected.get(k) != v} }\n"
            f"  已消失: {sorted(set(expected) - set(rep.address_mismatch))}\n"
            "新增差异说明生成器或金标准之一变了，需先核实再改清单。"
        )


def test_no_new_bit_discrepancies(reports: list[parity.McuParity]) -> None:
    for rep in reports:
        expected = KNOWN_BIT_DISCREPANCIES.get(rep.mcu, {})
        got = {f"{r}.{n}": v for (r, n), v in rep.bit_mismatch.items()}
        assert got == expected, (
            f"{rep.mcu}: 位号差异与冻结清单不符。\n"
            f"  新增/变化: "
            f"{ {k: v for k, v in got.items() if expected.get(k) != v} }\n"
            f"  已消失: {sorted(set(expected) - set(got))}\n"
            "新增差异说明生成器或金标准之一变了，需先核实再改清单。"
        )


def test_no_unknown_bit_names(reports: list[parity.McuParity]) -> None:
    """金标准的位名必须能在器件头里解析出来。

    位号对、位名错是最阴的一类：编译器只认宏名，`(1 << TXB08)` 根本编不过，
    而按位号比对永远发现不了。2026-09-16 靠这一项挖出 8 条转置错。
    """
    for rep in reports:
        got = {f"{r}.{n}" for r, n in rep.bit_names_unknown}
        expected = KNOWN_UNKNOWN_BIT_NAMES.get(rep.mcu, set())
        assert got == expected, (
            f"{rep.mcu}: 位名解析结果与冻结清单不符。\n"
            f"  新增: {sorted(got - expected)}\n"
            f"  已解决: {sorted(expected - got)}\n"
            "新增 = 金标准拼错了，或这是尚未登记的命名口径差异（后者应"
            "改 parity._field_known 的规则，而不是加进冻结表）。"
        )


def test_golden_is_sound(reports: list[parity.McuParity]) -> None:
    """总闸：覆盖性 + 值一致性 + 位名可解析，三者同时成立。"""
    for rep in reports:
        assert rep.sound, (
            f"{rep.mcu}: covered={rep.covered} consistent={rep.consistent} "
            f"unknown_names={rep.bit_names_unknown}"
        )


# --------------------------------------------------------------------------
# 3. 解析质量 —— 硬断言
# --------------------------------------------------------------------------


def test_conditional_filter_is_effective(reports: list[parity.McuParity]) -> None:
    """必须走「问 avr-gcc」这条路，否则家族共享头会串号。"""
    for rep in reports:
        assert rep.conditional_filter_applied, (
            f"{rep.mcu}: 条件过滤未生效（来源 {rep.register_source!r}）——"
            "生成器可能收进了同家族其他型号的寄存器。"
        )


def test_generated_set_is_superset(reports: list[parity.McuParity]) -> None:
    """生成器是覆盖全集，金标准是人工承诺子集，前者必然更大。"""
    for rep in reports:
        assert rep.generated_registers >= rep.golden_registers, rep.mcu
        assert rep.generated_bits >= rep.golden_bits, rep.mcu


def test_report_json_roundtrip(reports: list[parity.McuParity]) -> None:
    import json
    for rep in reports:
        json.dumps(rep.to_dict(), ensure_ascii=False)
