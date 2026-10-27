"""CMSIS 内核寄存器提取器（`core_cm7.h` → 知识库）。

守的是一条会让**所有做诊断/测量的项目永远卡在 30%** 的缺陷：

`SCB` / `NVIC` / `MPU` / `FPU` 在 SVD 里也有，但寄存器名是 SVD 自己的写法
（`CFSR_UFSR_BFSR_MMFSR`、`SHCRS`），源码写的是 `SCB->CFSR` / `SCB->SHCSR`，
查不到就被 S2 判成幻觉寄存器 → error → 源审查 FAIL → 置信度被硬压到 30%。
`DWT` / `CoreDebug` / `SysTick` / `ITM` / `TPI` 则**整个不在 SVD 里**。

这里的断言分两层：**解析结果**（寄存器名、地址、位域）与**交叉验证**
（结构体累加 vs 头文件注释偏移）。第三层验证在 `static_assert_source()`——
把偏移写成 `_Static_assert(offsetof(...))` 交给 gcc 判卷。
"""

from __future__ import annotations

import pytest

from firmforge.knowledge.extractors import cmsis_core as cm


@pytest.fixture(scope="module")
def core_header():
    path = cm.default_core_header()
    if path is None or not path.is_file():
        pytest.skip("本机没有 CMSIS Core 头（core_cm7.h）")
    return path


@pytest.fixture(scope="module")
def core_text(core_header):
    return core_header.read_text(encoding="utf-8", errors="replace")


@pytest.fixture(scope="module")
def groups(core_header):
    built, info = cm.build_core_groups(core_header)
    return built, info


# --------------------------------------------------------------------------
# 1. 基址宏
# --------------------------------------------------------------------------

def test_base_macros_resolve_offsets_and_indentation(core_text):
    """`SCB_BASE (SCS_BASE + 0x0D00UL)` 要能顺着引用算出来。

    `MPU_BASE` 写在 `#if defined (__MPU_PRESENT)` 里、**带缩进** —— 正则少
    `re.M` 或不容忍前导空白，MPU 整组就静默消失。
    """
    bases = cm.parse_base_addresses(core_text)
    assert bases["SCS_BASE"] == 0xE000E000
    assert bases["SCB_BASE"] == 0xE000ED00
    assert bases["MPU_BASE"] == 0xE000ED90
    assert bases["DWT_BASE"] == 0xE0001000
    assert bases["TPI_BASE"] == 0xE0040000


def test_peripheral_macros_give_group_type_and_base(core_text):
    """`#define SCB ((SCB_Type *) SCB_BASE)` 是组名/类型/基址的唯一权威出处。

    靠一张「组名 → 基址宏名」的硬编码表会错：`TPI_Type` 的基址宏叫
    `TPI_BASE`，而 `SCnSCB` 压根没有 `SCnSCB_BASE`，它直接用 `SCS_BASE`。
    """
    periphs = dict((g, (t, b)) for g, t, b in
                   cm.parse_peripheral_macros(core_text))
    assert periphs["SCB"] == ("SCB_Type", "SCB_BASE")
    assert periphs["TPI"] == ("TPI_Type", "TPI_BASE")
    assert periphs["SCnSCB"] == ("SCnSCB_Type", "SCS_BASE")
    assert "MPU" in periphs


# --------------------------------------------------------------------------
# 2. 结构体布局
# --------------------------------------------------------------------------

def test_struct_layout_matches_header_comments(groups):
    """「按 C 布局累加」与「头文件 `Offset: 0xNNN` 注释」是两套独立算法。

    不一致就是有一边错了，必须报出来 —— 静默取一边等于把错误藏进数据。
    """
    _built, info = groups
    assert info["offset_conflicts"] == []


def test_anonymous_union_is_sized_by_its_largest_member(core_text):
    """ITM 的 32 个激励端口是匿名 union。

    第一版按固定 `depth=1` 起算，union 没被正确收尾，扫描一路吃到文件尾，
    把 ITM 的成员算进了 DWT，DWT 的偏移整体差 4 字节（`CTRL: 0x4 ≠ 0x0`）。
    """
    structs, problems = cm.parse_structs(core_text)
    assert problems == []
    itm = {m["name"]: m["offset"] for m in structs["ITM_Type"]}
    assert itm["PORT"] == 0
    assert itm["TER"] == 0xE00


def test_dwt_offsets_are_not_shifted_by_itm(groups):
    built, _info = groups
    regs = {r["name"]: r["address"] for r in built["DWT"]["registers"]}
    assert regs["CTRL"] == "0xE0001000"
    assert regs["CYCCNT"] == "0xE0001004"


# --------------------------------------------------------------------------
# 3. 位域宏（`_Pos` 可能是表达式）
# --------------------------------------------------------------------------

def test_pos_expression_is_evaluated(core_text):
    """`#define SCB_CFSR_MMARVALID_Pos (SCB_CFSR_MEMFAULTSR_Pos + 7U)`。

    只认十进制字面量会把 CFSR 的 20 多个真实位域全丢掉，只剩 3 个分段别名
    —— 而那 20 多个才是崩溃转储要看的东西。
    """
    fields = {f["base"]: f for f in cm.parse_field_macros(core_text)}
    assert fields["SCB_CFSR_MMARVALID"]["bit"] == 7
    # IBUSERR 在 BFSR 段（bit 8 起）；MMARVALID 在 MMFSR 段（bit 7）。
    # 两段位号都靠 `(段基 + n)` 求值，只认字面量的话这两个都会丢。
    assert fields["SCB_CFSR_IBUSERR"]["bit"] == 8
    assert fields["SCB_CFSR_UNDEFINSTR"]["bit"] == 16
    assert all(f.get("bit") is not None for f in fields.values()
               if not f["base"].startswith("_")), "有空位号说明求值漏了"


def test_field_width_comes_from_mask(core_text):
    fields = {f["base"]: f for f in cm.parse_field_macros(core_text)}
    assert fields["SCB_CFSR_MMARVALID"]["bit_width"] == 1
    assert fields["SCB_SHCSR_MEMFAULTENA"]["bit_width"] == 1


# --------------------------------------------------------------------------
# 4. 组装：源码里真正出现的名字必须都能查到
# --------------------------------------------------------------------------

def test_expected_groups_are_all_present(groups):
    built, info = groups
    assert info["problems"] == [], \
        f"有内核组没收录：{info['problems']}"
    for name in cm.EXPECTED_GROUPS:
        assert name in built, f"{name} 缺失"
        assert built[name]["registers"], f"{name} 没有寄存器"


@pytest.mark.parametrize("group, register, address", [
    # 崩溃转储的核心三件套
    ("SCB", "CFSR", "0xE000ED28"),
    ("SCB", "HFSR", "0xE000ED2C"),
    ("SCB", "SHCSR", "0xE000ED24"),      # SVD 里拼成 SHCRS
    ("SCB", "MMFAR", "0xE000ED34"),
    # 周期计时 / 指令计数
    ("DWT", "CYCCNT", "0xE0001004"),
    ("DWT", "CTRL", "0xE0001000"),
    # 调试使能
    ("CoreDebug", "DEMCR", "0xE000EDFC"),
    # 中断控制
    ("NVIC", "ISER", "0xE000E100"),
    ("SCnSCB", "ACTLR", "0xE000E008"),
    ("SysTick", "LOAD", "0xE000E014"),
    ("ITM", "TER", "0xE0000E00"),
    ("MPU", "CTRL", "0xE000ED94"),
    ("FPU", "FPCCR", "0xE000EF34"),
])
def test_key_registers_are_addressable(groups, group, register, address):
    built, _info = groups
    regs = {r["name"]: r for r in built[group]["registers"]}
    assert register in regs, f"{group}.{register} 不在库里（源码里就是这么写的）"
    assert regs[register]["address"] == address


def test_scb_cfsr_carries_the_real_bit_fields(groups):
    """`SCB->CFSR` 要能回答「哪一位是 IBUSERR」。

    第一版把 CFSR 只收成 3 个分段别名（`MEMFAULTSR` / `BUSFAULTSR` /
    `USGFAULTSR`），崩溃转储根本没法用。
    """
    built, _info = groups
    cfsr = next(r for r in built["SCB"]["registers"] if r["name"] == "CFSR")
    names = {f["name"] for f in cfsr["fields"]}
    assert len(cfsr["fields"]) >= 20, f"CFSR 位域只有 {len(cfsr['fields'])} 个"
    assert {"SCB_CFSR_IBUSERR", "SCB_CFSR_PRECISERR",
            "SCB_CFSR_MMARVALID", "SCB_CFSR_IMPRECISERR"} <= names


def test_field_names_are_the_macros_used_in_source(groups):
    """位域名取**宏基名**（`SCB_CFSR_IBUSERR`），不是 SVD 的裸名（`IBUSERR`）：
    源码里出现的是前者。SVD 的写法若要保留，进 `svd_name`。"""
    built, _info = groups
    cfsr = next(r for r in built["SCB"]["registers"] if r["name"] == "CFSR")
    for field in cfsr["fields"]:
        assert field["name"].startswith("SCB_CFSR_"), field["name"]
        assert field["name_source"] == "cmsis_macro"


def test_svd_name_differences_are_recorded_not_silently_dropped(core_header):
    """SVD 与 CMSIS 名字不一致的地方必须留痕（`SHCRS` 是 SVD 自己的拼写错）。

    不传 SVD 组时不许编造差异 —— 空列表就是空列表。
    """
    _plain, plain_info = cm.build_core_groups(core_header)
    assert plain_info["svd_name_differences"] == []

    _built, info = cm.build_core_groups(core_header, svd_groups={
        "SCB": {"registers": [
            {"name": "SHCRS", "address": "0xE000ED24", "size": 32},
            {"name": "CFSR_UFSR_BFSR_MMFSR", "address": "0xE000ED28",
             "size": 32}]}})
    notes = " ".join(info["svd_name_differences"])
    assert "SCB.SHCSR ← SVD 写作 SHCRS" in notes
    assert "CFSR_UFSR_BFSR_MMFSR" in notes


def test_svd_groups_are_only_used_for_cross_checking(groups, core_header):
    """传进去的 SVD 组只用来补 `svd_name` / `description`，绝不覆盖 CMSIS 名。

    否则「知识库里存的还是 `SHCRS`」这件事会静默成立，源码写 `SHCSR` 又查不到。
    """
    built, _info = cm.build_core_groups(core_header, svd_groups={
        "SCB": {"registers": [
            {"name": "SHCRS", "address": "0xE000ED24", "size": 32,
             "fields": [{"name": "MEMFAULTENA", "bit": 16}]}]}})

    scb = {r["name"] for r in built["SCB"]["registers"]}
    assert "SHCSR" in scb, "CMSIS 的成员名被 SVD 的写法顶掉了"
    assert "SHCRS" not in scb, "SVD 的拼写错误不许进寄存器名"

    shcsr = next(r for r in built["SCB"]["registers"] if r["name"] == "SHCSR")
    memfaultena = next(f for f in shcsr["fields"]
                       if f["name"] == "SCB_SHCSR_MEMFAULTENA")
    # 位域名字取 CMSIS 宏名，SVD 的裸名留 svd_name
    assert memfaultena.get("svd_name") == "MEMFAULTENA"


# --------------------------------------------------------------------------
# 5. 让编译器给偏移判卷
# --------------------------------------------------------------------------

def test_static_assert_source_guards_against_vendor_macro_clash(core_header):
    """`offsetof(DWT_Type, COMP1)` 会被 `stm32h743xx.h` 的 `COMP1`
    （比较器外设指针）宏展开成语法错误 —— 必须先 `#undef` 再断言。"""
    src = cm.static_assert_source(core_header)
    assert "_Static_assert(offsetof(SCB_Type, CFSR) == 0x28" in src
    assert "#undef COMP1" in src
    # 断言行数要覆盖全部非保留成员
    assert src.count("_Static_assert(offsetof(") >= 130
