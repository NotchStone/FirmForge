"""STM32 器件头解析与 SVD↔器件头 比对 测试。

分两层：

1. **解析器单元测试**（`synthetic_header`）—— 用一份手写的小器件头把
   `stm32_devheader` 的每条规则钉住：基址宏求值形态、结构体累计偏移、
   `_Msk` 位宽、四级位域查找、实例作用域筛选、前缀别名。
   不依赖任何外部文件，所以永远会跑。
2. **真实器件头集成测试** —— 拿本机的 SVD 与 `stm32h743xx.h` 跑一遍，
   把**已裁定缺陷**与**已知未裁定项**冻结成表：新差异会被测试拦住。
   文件不在则跳过（跳过 = 这道防线当次不生效，所以别长期依赖跳过）。

冻结表的意义和 AVR 侧 `test_knowledge_golden.py` 一样：机制留着，
现状钉住，**新增即失败**；修掉一条就删一条。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from firmforge.knowledge import parity
from firmforge.knowledge.extractors import stm32_devheader as dev

REPO_ROOT = Path(__file__).resolve().parent.parent

SYNTHETIC = """\
#define PERIPH_BASE            (0x40000000UL)
#define APB1_BASE              PERIPH_BASE
#define APB2_BASE              (PERIPH_BASE + 0x00010000UL)

#define UART1_BASE             (APB2_BASE + 0x1000UL)
#define FLASH_R_BASE           (PERIPH_BASE + 0x2000UL)
#define UART2_BASE             UART1_BASE

typedef struct
{
  __IO uint32_t CR1;
  __IO uint32_t SR;
  uint32_t      RESERVED0;
  __IO uint32_t CR2;
} UART_TypeDef;

typedef struct
{
  __IO uint32_t ACR;
  __IO uint32_t KEYR1;
  uint32_t      RESERVED[3];
  __IO uint32_t CR1;
} FLASH_TypeDef;

#define UART1               ((UART_TypeDef *) UART1_BASE)
#define UART2               ((UART_TypeDef *) UART2_BASE)
#define FLASH               ((FLASH_TypeDef *) FLASH_R_BASE)

#define UART_CR1_UE_Pos                 (0U)
#define UART_CR1_UE_Msk                 (0x1UL << UART_CR1_UE_Pos)
#define UART_CR1_WL_Pos                 (12U)
#define UART_CR1_WL_Msk                 (0x3UL << UART_CR1_WL_Pos)

/* 10 位的整体字段 —— 用来验证 digit 档不会把它对到逐位展开的 SADD1..9 */
#define I2C_CR2_SADD_Pos                (0U)
#define I2C_CR2_SADD_Msk                (0x3FFUL << I2C_CR2_SADD_Pos)
#define I2C_CR2_SADD1_Pos               (1U)
#define I2C_CR2_SADD1_Msk               (0x1UL << I2C_CR2_SADD1_Pos)

/* 单 bit 字段 —— digit 档应当接受 */
#define UART_CR2_STOP_Pos               (12U)
#define UART_CR2_STOP_Msk               (0x1UL << UART_CR2_STOP_Pos)

/* 词边界前缀：RXNE 应能配到 RXNE_RXFNE，但 TEFL 不能配到 TEFLL */
#define UART_SR_RXNE_RXFNE_Pos          (5U)
#define UART_SR_RXNE_RXFNE_Msk          (0x1UL << UART_SR_RXNE_RXFNE_Pos)
#define UART_SR_TEFLL_Pos               (15U)
#define UART_SR_TEFLL_Msk               (0x1UL << UART_SR_TEFLL_Pos)

/* 前缀别名：器件头里没有 LPUART_* 宏，靠 USART_* */
#define UART2_LPUART_ALIAS_MARK         (0U)
"""


@pytest.fixture(scope="module")
def synthetic_header(tmp_path_factory) -> dev.DeviceHeader:
    path = tmp_path_factory.mktemp("hdr") / "synthetic.h"
    path.write_text(SYNTHETIC, encoding="utf-8")
    return dev.parse_device_header(path)


# --------------------------------------------------------------------------
# 解析器
# --------------------------------------------------------------------------


def test_instance_pointers_parsed(synthetic_header: dev.DeviceHeader) -> None:
    assert set(synthetic_header.instances) == {"UART1", "UART2", "FLASH"}
    assert synthetic_header.instances["UART1"].struct == "UART_TypeDef"
    assert synthetic_header.instances["UART1"].base_macro == "UART1_BASE"


def test_base_macro_chain_resolves(synthetic_header: dev.DeviceHeader) -> None:
    """三种宏体形态都要能求值：字面量 / 父+偏移 / 裸引用。"""
    assert synthetic_header.base_address("UART1") == 0x40011000
    assert synthetic_header.base_address("UART2") == 0x40011000
    assert synthetic_header.base_address("FLASH") == 0x40002000


def test_struct_offsets_use_cumulative_width(
        synthetic_header: dev.DeviceHeader) -> None:
    """偏移按累计宽度算 —— 保留字与数组都占位，不能数成员个数乘 4。"""
    assert synthetic_header.members("UART_TypeDef") == {
        "CR1": 0x00, "SR": 0x04, "CR2": 0x0C,
    }
    assert synthetic_header.members("FLASH_TypeDef") == {
        "ACR": 0x00, "KEYR1": 0x04, "CR1": 0x14,
    }


def test_field_width_comes_from_mask(synthetic_header: dev.DeviceHeader) -> None:
    assert synthetic_header.field_width["UART_CR1_UE"] == 1
    assert synthetic_header.field_width["UART_CR1_WL"] == 2
    assert synthetic_header.field_width["I2C_CR2_SADD"] == 10


def test_lookup_exact_stage(synthetic_header: dev.DeviceHeader) -> None:
    assert synthetic_header.lookup_field("CR1", "UE", "UART1", "UART1",
                                         "UART") == (0, "exact")


def test_lookup_rejects_non_single_bit_digit_match(
        synthetic_header: dev.DeviceHeader) -> None:
    """`SADD1` 是 10 位整体字段的第 1 位，**不能**对到 SADD。

    对上去就会报出「SVD=1 vs 器件头=0」这种假冲突 —— 实测 157 条假冲突
    里有九成是这一类。
    """
    value, how = synthetic_header.lookup_field("CR2", "SADD1", "UART1",
                                               "UART1", "UART")
    assert how != "digit"


def test_lookup_accepts_single_bit_digit_match(
        synthetic_header: dev.DeviceHeader) -> None:
    """单 bit 字段的编号差异要接受（SVD `STOP1` ↔ 器件头 `STOP`）。"""
    assert synthetic_header.lookup_field("CR2", "STOP1", "UART1", "UART1",
                                         "UART") == (12, "digit")


def test_lookup_prefix_requires_token_boundary(
        synthetic_header: dev.DeviceHeader) -> None:
    """`RXNE` → `RXNE_RXFNE` 可以；`TEFL` → `TEFLL` 不行（一位转置）。"""
    assert synthetic_header.lookup_field("SR", "RXNE", "UART1", "UART1",
                                         "UART") == (5, "prefix")
    assert synthetic_header.lookup_field("SR", "TEFL", "UART1", "UART1",
                                         "UART")[1] == "none"


def test_lookup_does_not_borrow_other_peripheral(
        synthetic_header: dev.DeviceHeader) -> None:
    """筛空时**不许**退回全局池：`FLASH.CR1.###` 不能借到别的外设的位号。"""
    value, how = synthetic_header.lookup_field("CR1", "WL", "FLASH", "FLASH",
                                               "FLASH")
    assert how == "none" and value is None


def test_scope_match_handles_case_and_family(synthetic_header) -> None:
    assert dev.scope_match("UART_CR1_UE", "UART1", "UART1", "UART")
    assert dev.scope_match("UART_CR1_UE", "UART2", "UART2", "UART")
    assert not dev.scope_match("I2C_CR2_SADD", "UART1", "UART1", "UART")
    # 归一化：器件头 `FLASH_` vs SVD `Flash`
    assert dev.scope_match("FLASH_ACR_LATENCY", "FLASH", "Flash", "Flash")


def test_prefix_alias_covers_lpuart() -> None:
    """H743 器件头没有 `LPUART_*` 宏，LPUART1 靠 `USART_*`。"""
    assert dev.scope_match("USART_CR1_UE", "LPUART1", "LPUART1", "LPUART")
    assert dev.scope_match("LPUART_CR1_UE", "LPUART1", "LPUART1", "LPUART")


def test_glob_only_one_star() -> None:
    assert parity._glob("DINR*", "DINR12")
    assert parity._glob("AWD*CH", "AWD3CH")
    assert parity._glob("AWD*CR", "AWD3CR")
    assert not parity._glob("AWD*CR", "AWD3C")
    assert not parity._glob("DINR*", "DOUTR0")


def test_known_issue_delta_semantics() -> None:
    """已知缺陷用**增量**判定，不用绝对地址 —— 换芯片不该全表失效。"""
    ki = parity.KnownIssue(peripheral="X", register="R", kind="offset",
                           delta=+4)
    assert ki.matches(100, 104)
    assert not ki.matches(100, 108)
    shift = parity.KnownIssue(peripheral="X", register="R", kind="bit_shift",
                              delta=+4)
    assert shift.matches(0, 4) and shift.matches(11, 15)
    assert not shift.matches(0, 3)


# --------------------------------------------------------------------------
# 真实器件头
# --------------------------------------------------------------------------

#: 已裁定缺陷 —— 冻结条数。新增/消失都要在这里同步。
EXPECTED_KNOWN_HITS = 15

#: 仍需人工裁定的「同名不同值」—— 冻结成表，**新增即失败**。
#: 目前只剩 1 条：器件头说 RXCHCNT 是 3 位 @13，SVD 说 4 位 @12，
#: 两边各自的表都自洽，靠现有两个来源分不出谁对（要查手册 bit 定义）。
KNOWN_UNADJUDICATED_MISMATCHES = {
    "Ethernet_MAC.MACHWF2R.RXCHCNT": (12, 13),
}


@pytest.fixture(scope="module")
def stm32_report() -> parity.Stm32Parity:
    svd = parity.find_svd("STM32H743x.svd", REPO_ROOT)
    header = parity.default_cmsis_include() / "stm32h743xx.h"
    if svd is None:
        pytest.skip("SVD 不在 ~/.firmforge/cache/knowledge/_sources/")
    if not header.is_file():
        pytest.skip(f"器件头不存在：{header}")
    return parity.compare_stm32(svd, header)


def test_no_base_address_mismatch(stm32_report: parity.Stm32Parity) -> None:
    """基址是硬事实：不一致就是有人错，不许有例外。"""
    assert stm32_report.base_mismatch == {}


def test_no_offset_mismatch(stm32_report: parity.Stm32Parity) -> None:
    """绝对地址不一致 = 硬错。当前全部已裁定进缺陷表。"""
    assert stm32_report.offset_mismatch == {}


def test_bit_mismatches_are_the_known_ones(
        stm32_report: parity.Stm32Parity) -> None:
    assert stm32_report.bits_mismatch == KNOWN_UNADJUDICATED_MISMATCHES


def test_known_issue_table_is_not_stale(
        stm32_report: parity.Stm32Parity) -> None:
    """缺陷表每条都必须命中 —— 没命中说明值变了、要重新裁定。"""
    assert stm32_report.known_stale == []
    assert len(stm32_report.known_hits) == EXPECTED_KNOWN_HITS


def test_every_peripheral_is_accounted_for(
        stm32_report: parity.Stm32Parity) -> None:
    """每个 SVD 外设要么比过了、要么在某个带理由的桶里 —— 不许无声消失。"""
    total = (stm32_report.mapped_peripherals + len(stm32_report.unmapped)
             + len(stm32_report.no_instance)
             + len(stm32_report.skipped_core))
    assert total == stm32_report.svd_peripherals
    assert stm32_report.unmapped == []


def test_no_ambiguous_field_resolution(stm32_report: parity.Stm32Parity) -> None:
    """只剩 DMA2D.OCOLR 的 3 个（RED/GREEN/ALPHA 在两个外设里位号不同）。

    歧义必须被**报告**，不能静默取一个值 —— 这条测试就是那道闸门。
    """
    for name in stm32_report.bits_ambiguous:
        assert name.startswith("DMA2D.")


def test_structural_exemptions_carry_reasons(
        stm32_report: parity.Stm32Parity) -> None:
    for pn in stm32_report.structural_exempt:
        assert pn in parity.STRUCTURAL_DIFFERENCES, pn
        assert parity.STRUCTURAL_DIFFERENCES[pn].strip()


def test_report_json_roundtrip(stm32_report: parity.Stm32Parity) -> None:
    import json
    data = json.loads(json.dumps(stm32_report.to_dict(), ensure_ascii=False))
    assert data["mcu"] == "stm32h743zit6"
    assert data["counts"]["svd_peripherals"] == 128


def test_render_text_mentions_the_defects(
        stm32_report: parity.Stm32Parity) -> None:
    text = parity.render_stm32_text([stm32_report])
    assert "已裁定 SVD 缺陷" in text
    assert "BDMA.ISR" in text
