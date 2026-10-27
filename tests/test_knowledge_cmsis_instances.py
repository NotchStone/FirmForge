"""CMSIS 器件头的外设**实例视图**（`stm32h743xx.h` → 知识库）。

守的是 SVD 在**实例名**上的结构性缺口。SVD 与器件头对同一颗芯片的切分方式
不同，源码只认后者的写法：

| | SVD | `stm32h743xx.h` |
|:--|:--|:--|
| DMA 通道 | `DMA1` 一个外设，寄存器 `S0CR` / `S1CR` | `DMA1_Stream0..7` 独立指针，寄存器都叫 `CR` |
| 看门狗 | `IWDG` | `IWDG1` |
| 比较器 | `COMP1` 5 个寄存器（`SR`/`ICFR`/`OR`/`CFGR1`/`CFGR2`） | `COMP1->CFGR` / `COMP2->CFGR` |

实测 H743 上有 139 个「器件头有、库里没有」的实例名。这条与 `SCB.CFSR`
是同一个病根：**SVD 不是可靠孤证**，实例名与寄存器名得以器件头为准。

本文件盯三类东西，任何一类失守都会让知识库**静默地**放出幻觉寄存器：
  1. 收全（`DMA1_Stream0->CR`、`IWDG1->KR` 查得到）
  2. 不收多（`TIM6->CCMR1` 必须查不到 —— 基本定时器没这个寄存器）
  3. 别名合并（`TIM2->CCMR1` 对上 SVD 的 `CCMR1_Output`）
"""

from __future__ import annotations

import pytest

from firmforge.knowledge.extractors import cmsis_core as cm
from firmforge.knowledge.extractors import cmsis_instances as ci


@pytest.fixture(scope="module")
def device_header():
    path = ci.default_device_header()
    if path is None or not path.is_file():
        pytest.skip("本机没有器件头（stm32h743xx.h）")
    return path


@pytest.fixture(scope="module")
def device_text(device_header):
    return device_header.read_text(encoding="utf-8", errors="replace")


@pytest.fixture(scope="module")
def built(device_header):
    return ci.build_instance_groups(device_header)


# --------------------------------------------------------------------------
# 0. 器件头定位（生成器默认路径）
# --------------------------------------------------------------------------

def test_device_header_is_locatable(device_header):
    """生成器得能自己找到器件头，否则默认行为就是「少一块数据」。"""
    assert device_header.is_file()
    assert "stm32h7" in device_header.name.lower()


# --------------------------------------------------------------------------
# 1. 成员限定符：`__IO` / `__I` / `__O` 一个都不能漏
# --------------------------------------------------------------------------

def test_all_access_qualifiers_are_parsed(device_text):
    """`__I` / `__O` 漏掉会让后面**全部**成员偏移前移，且不报错。

    实例：`SDMMC_TypeDef` 的 `DCOUNT` / `STA` / `RESPCMD` / `RESP1..3` 都是
    `__I`。当初 `_MEMBER_RE` 只认内核头那套 `__IOM/__IM/__OM`，导致
    `DTIMER` 之后所有偏移差 0x14 —— 936 条 `_Static_assert` 里 60 多条直接
    判失败，才把这个问题逼出来。**不报错的错位是最难查的形态**。
    """
    structs, _problems = cm.parse_structs(device_text)
    members = {m["name"]: m for m in structs["SDMMC_TypeDef"]}
    assert "DCOUNT" in members and members["DCOUNT"]["access"] == "ro"
    assert "STA" in members and members["STA"]["access"] == "ro"
    assert "RESP1" in members
    # `__IO` 的读写属性也要认
    assert members["POWER"]["access"] == "rw"


def test_bare_alias_base_macro_resolves(device_text):
    """`#define D2_APB1PERIPH_BASE  PERIPH_BASE` —— 无括号的纯别名。

    `_BASE_RE` 原先强制要求 `(...)`，这一条匹配不到 → 整条依赖链断掉 →
    `DAC1` / `OPAMP1` / `SWPMI1` / `FDCAN_CCU` 四个外设被静默跳过。
    """
    bases = cm.parse_base_addresses(device_text)
    assert bases.get("D2_APB1PERIPH_BASE") == 0x40000000
    assert bases.get("DAC1_BASE") == 0x40007400


# --------------------------------------------------------------------------
# 2. 收全：源码里会这么写
# --------------------------------------------------------------------------

@pytest.mark.parametrize("instance,register,address", [
    ("DMA1_Stream0", "CR", "0x40020010"),
    ("DMA1_Stream7", "FCR", "0x400200CC"),
    ("BDMA_Channel0", "CCR", "0x58025408"),
    ("IWDG1", "KR", "0x58004800"),
    ("WWDG1", "CR", "0x50003000"),
    ("DBGMCU", "IDCODE", "0x5C001000"),
    ("DFSDM1_Filter0", "FLTCR1", "0x40017100"),
])
def test_instance_registers_are_present(built, instance, register, address):
    groups, _info = built
    assert instance in groups, f"{instance} 没被收录 —— 源码这么写会被判幻觉"
    hits = {r["name"]: r["address"] for r in groups[instance]["registers"]}
    assert hits.get(register) == address


def test_instance_address_cross_checks_against_svd(built):
    """`DMA1_Stream0.CR` 与 SVD 的 `DMA1.S0CR` 必须同地址。

    两条独立来源给出同一个地址，才说明「结构体累加 + 基址求值」没算错。
    """
    groups, _info = built
    cr = next(r for r in groups["DMA1_Stream0"]["registers"]
              if r["name"] == "CR")
    assert cr["address"] == "0x40020010", "SVD 的 DMA1.S0CR 也在 0x40020010"


# --------------------------------------------------------------------------
# 3. 不收多：共用结构体不能给基本定时器造寄存器
# --------------------------------------------------------------------------

def test_shared_struct_does_not_inflate_basic_timers():
    """`TIM6` / `TIM7` 与 TIM2 共用 `TIM_TypeDef`，但硬件上**没有** CCMR。

    这是本模块最危险的失败模式：全量收录会让 `TIM6->CCMR1` 通过审查 ——
    本该被拦下的幻觉寄存器被知识库放行，比漏收危害大得多。
    判据：SVD 的同名组不认这个地址就不收。
    """
    import json
    from pathlib import Path

    from firmforge.knowledge.extractors import stm32_registers as gen

    path = gen.registers_path("stm32h743zit6", series="stm32h7")
    if not path.is_file():
        pytest.skip("B 区没有已生成的 registers.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    groups = data["register_groups"]

    def names(group):
        return {r["name"] for r in groups[group]["registers"]}

    # 通用定时器有 CCMR1
    assert "CCMR1" in names("TIM2"), "TIM2 有 CCMR1，漏了就少审一个寄存器"
    # 基本定时器没有 —— 结构体里有，硬件上没有
    for basic in ("TIM6", "TIM7"):
        assert "CCMR1" not in names(basic), (
            f"{basic} 是基本定时器，没有 CCMR1；收进来等于放行幻觉寄存器")
        assert "CCMR2" not in names(basic)


# --------------------------------------------------------------------------
# 4. 别名合并：SVD 拆视图，源码用基名
# --------------------------------------------------------------------------

def test_svd_split_views_are_merged():
    """SVD 把 `CCMR1` 拆成 `CCMR1_Output` / `CCMR1_Input`，源码只写 `CCMR1`。

    不合并 → `TIM2->CCMR1` 判幻觉。合并后两个名字都在库里，两种写法都能过。
    """
    import json

    from firmforge.knowledge.extractors import stm32_registers as gen

    path = gen.registers_path("stm32h743zit6", series="stm32h7")
    if not path.is_file():
        pytest.skip("B 区没有已生成的 registers.json")
    groups = json.loads(path.read_text(encoding="utf-8"))["register_groups"]
    names = {r["name"] for r in groups["TIM2"]["registers"]}
    assert "CCMR1" in names, "器件头写的 CCMR1 没并进来"
    assert any(n.startswith("CCMR1") and n != "CCMR1" for n in names), (
        "SVD 那边的拆分名被丢掉了 —— 合并应当是追加，不是替换")


def test_comp_alias_covers_cmsis_name():
    """`COMP1->CFGR`：SVD 把 COMP1 的 5 个寄存器都记在这一组下，却叫 `CFGR1`。"""
    import json

    from firmforge.knowledge.extractors import stm32_registers as gen

    path = gen.registers_path("stm32h743zit6", series="stm32h7")
    if not path.is_file():
        pytest.skip("B 区没有已生成的 registers.json")
    groups = json.loads(path.read_text(encoding="utf-8"))["register_groups"]
    comp1 = {r["name"]: r["address"] for r in groups["COMP1"]["registers"]}
    assert comp1.get("CFGR") == "0x5800380C", "CMSIS 的 COMP1->CFGR"


# --------------------------------------------------------------------------
# 5. 交叉验证：注释偏移的两种基准
# --------------------------------------------------------------------------

def test_sub_block_instances_are_not_flagged_as_conflict():
    """`SAI1_Block_A` 的注释写的是**相对 SAI1_BASE** 的偏移（CR1 标 0x04），
    而结构体内累加是 0x00 —— 差值恒定，是基准不同，不是错。

    逐个成员硬比会把 SAI 的 32 个成员全报成冲突，等于把「校验」变成噪声。
    """
    groups, info = ci.build_instance_groups(ci.default_device_header())
    assert "SAI1_Block_A" in groups
    notes = " ".join(info["base_offset_notes"])
    assert "SAI1_Block_A" in notes
    assert not any("SAI1_Block_A" in c for c in info["offset_conflicts"])


def test_real_offset_conflict_is_reported(built):
    """`LTDC_Layer` 的 `CLUTWR` 注释写 0x144，其余成员基准是 0x84 ——
    差值不恒定，是真冲突（厂商注释笔误），必须报出来。"""
    _groups, info = built
    conflicts = " ".join(info["offset_conflicts"])
    assert "LTDC_Layer1" in conflicts and "CLUTWR" in conflicts


# --------------------------------------------------------------------------
# 6. 静态断言源：偏移交给 gcc 判卷
# --------------------------------------------------------------------------

def test_static_assert_source_covers_every_instance_type(device_header):
    """936 条 `_Static_assert(offsetof(...))` —— 偏移不再是「我算的」。"""
    source = ci.static_assert_source(device_header)
    assert source.count("_Static_assert(offsetof(") > 900
    # 成员名与厂商宏同名时必须先 #undef，否则宏展开成语法错误
    assert "#undef" in source
