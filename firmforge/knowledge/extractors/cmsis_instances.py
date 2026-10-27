"""CMSIS 器件头的外设**实例视图** —— 补 SVD 在实例名上的结构性缺口。

## 为什么需要这一层

SVD 与器件头对同一颗芯片的**切分方式不同**，两边都「对」，但源码只认后者：

| | SVD | `stm32h743xx.h` |
|:--|:--|:--|
| DMA 通道 | 一个 `DMA1` 外设，寄存器拍平编号 `S0CR` / `S1CR` / … | `DMA1_Stream0` … `DMA1_Stream7` 各是一个独立指针宏，寄存器都叫 `CR` / `NDTR` / `PAR` |
| 看门狗 | `IWDG` | `IWDG1`（H7 有两个） |
| 比较器 | `COMP` | `COMP1` / `COMP2` |

源码写的是 `DMA1_Stream0->CR`、`IWDG1->KR`。只按 SVD 建库，这些引用查不到 →
判成幻觉寄存器 → 源审查 FAIL → Confidence 被硬压。实测 H743 上有 **139 个**
这样「器件头有、库里没有」的实例名，DMA / BDMA / DFSDM / IWDG1 / DAC1 /
DBGMCU / COMP2 全在其中。

这与 `SCB.CFSR`（SVD 写作 `CFSR_UFSR_BFSR_MMFSR`）是同一个病根：**SVD 不是
可靠孤证**，实例名与寄存器名得以器件头为准。

## 权威性怎么保证

三层，缺一不可：

1. **结构体布局**按 C 规则累加偏移（`cmsis_core.parse_structs`）。
2. **头文件 `Address offset: 0xNN` 注释**独立算一遍，与累加结果比对；
   不一致记 `offset_conflicts`，不静默选一边。
3. **SVD 绝对地址**做第三方交叉验证：`基址 + 偏移` 必须能落到 SVD 里某个
   真实寄存器的地址上。落不上的记 `address_not_in_svd` —— 可能是 SVD 没收
   录，也可能是我算错了，两者都不许沉默。

基址宏是多层引用的（`PERIPH_BASE` → `D2_AHB1PERIPH_BASE` → `DMA1_BASE`
→ `DMA1_Stream0_BASE`），靠 `parse_base_addresses` 按轮次迭代求值；求不出
就跳过并留痕，**不猜默认值**。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable

from firmforge.knowledge.extractors.cmsis_core import (
    parse_base_addresses,
    parse_structs,
)

PARSER_VERSION = "cmsis-instances/1.0.0"

#: `#define DMA1_Stream0     ((DMA_Stream_TypeDef *) DMA1_Stream0_BASE)`
#:
#: 组名、类型、基址三件事在这一行里同时给出，所以它是**唯一权威出处** ——
#: 不另维护一张「实例名 → 类型」表（`cmsis_core` 曾经因为手写表把 `TPI` 记成
#: `TPIU_BASE`、把 `SCnSCB` 记成不存在的 `SCnSCB_BASE` 而漏收两个组）。
_INSTANCE_RE = re.compile(
    r"^[ \t]*#[ \t]*define[ \t]+([A-Za-z_]\w*)[ \t]+"
    r"\(\([ \t]*([A-Za-z_]\w*)_TypeDef[ \t]*\*[ \t]*\)[ \t]*"
    r"([A-Za-z_]\w*)[ \t]*\)",
    re.M,
)


def parse_instances(text: str) -> list[tuple[str, str, str]]:
    """解析外设指针宏 → `[(实例名, 类型名, 基址宏名)]`。"""
    return [(m.group(1), f"{m.group(2)}_TypeDef", m.group(3))
            for m in _INSTANCE_RE.finditer(text)]


def build_instance_groups(
    device_header: Path | str,
    *,
    svd_groups: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """产出「器件头独有实例」的 `register_groups` 片段 + 统计/问题。

    Args:
        device_header: `stm32h743xx.h` 一类的器件头。
        svd_groups: 已由 SVD 生成的组。**同名组一律让给 SVD** —— 那边有位域
            描述与访问属性，信息更全；这里只补 SVD 没有的实例名。

    Returns:
        `(groups, info)`。`info` 供 `_generator` 落盘与人工核对。
    """
    path = Path(device_header)
    text = path.read_text(encoding="utf-8", errors="replace")
    bases = parse_base_addresses(text)
    structs, struct_problems = parse_structs(text)
    instances = parse_instances(text)
    svd_groups = svd_groups or {}

    # SVD 绝对地址 → "组.寄存器"，做第三方交叉验证
    svd_by_addr: dict[int, str] = {}
    for group_name, group in svd_groups.items():
        for reg in group.get("registers", []):
            try:
                addr = int(reg["address"], 16)
            except (KeyError, TypeError, ValueError):
                continue
            svd_by_addr.setdefault(addr, f"{group_name}.{reg.get('name', '?')}")

    groups: dict[str, Any] = {}
    problems: list[str] = list(struct_problems)
    offset_conflicts: list[str] = []
    base_offset_notes: list[str] = []
    svd_name_notes: list[str] = []
    address_not_in_svd: list[str] = []
    unmodeled_by_svd: list[str] = []
    n_regs = 0
    aliases = 0
    merged_into_svd = 0

    for instance, type_name, base_macro in instances:
        existing = svd_groups.get(instance)
        members = structs.get(type_name)
        if not members:
            problems.append(f"{instance}: 头文件里没有 {type_name} 的成员定义（跳过）")
            continue
        base = bases.get(base_macro)
        if base is None:
            problems.append(f"{instance}: 求不出基址 {base_macro}（跳过）")
            continue

        # SVD 同名组已承认的**地址**集合。
        #
        # 这个集合是「共用结构体」的护栏，不是可有可无的优化：
        # `TIM6` / `TIM7` 是基本定时器，但它们和 TIM2 共用 `TIM_TypeDef`，
        # 结构体里照样有 `CCMR1` / `CCMR2`。全量收录会给 TIM6 造出 18 个
        # **硬件上不存在**的寄存器 —— 源码写 `TIM6->CCMR1` 本该被拦下，
        # 结果被知识库放行，比漏收危害大得多。
        # 所以对 SVD 已有的组，只允许「同地址别名」（`TIM2->CCMR1` 对上 SVD
        # 的 `CCMR1_Output`），不允许新增地址。
        existing_addrs: set[int] = set()
        if existing is not None:
            for reg in existing.get("registers", []):
                try:
                    existing_addrs.add(int(reg["address"], 16))
                except (KeyError, TypeError, ValueError):
                    continue

        regs: list[dict[str, Any]] = []
        # 交叉验证一：注释偏移 vs C 布局累加。
        #
        # **不能逐个成员直接比**：器件头注释里的偏移有两种基准 ——
        #   · 多数实例：相对实例指针本身（不等 → 真冲突）
        #   · 子块实例：相对**父外设**基址。SAI1_Block_A 的第一个成员
        #     CR1 注释写 `Address offset: 0x04`，而 `SAI1_Block_A_BASE` 本身
        #     就是 `SAI1_BASE + 0x4` —— 结构体内累加当然是 0x00。
        #     DFSDM1_Filter0 更极端：整体差 0x100。
        # 判据：同一实例内 `注释 - 累加` 的差值**恒定** → 基准不同，不是错；
        # 差值不恒定 → 真有成员被漏算或算错。
        diffs: dict[int, list[str]] = {}
        for member in members:
            comment = member.get("comment_offset")
            if comment is None:
                continue
            diffs.setdefault(comment - member["offset"], []).append(
                member["name"])
        if len(diffs) > 1:
            main = max(diffs, key=lambda k: len(diffs[k]))
            for diff, names in diffs.items():
                if diff != main:
                    offset_conflicts.append(
                        f"{instance}: {', '.join(names[:4])} 的注释偏移比"
                        f"累加偏移多 0x{diff:X}，与多数成员（0x{main:X}）不一致")
        elif diffs:
            only = next(iter(diffs))
            if only:
                base_offset_notes.append(
                    f"{instance}: 注释偏移整体比累加多 0x{only:X}"
                    f"（实例基址是父外设的子偏移，非错误）")

        for member in members:
            if member["name"].startswith("RESERVED"):
                continue

            addr = base + member["offset"]
            entry: dict[str, Any] = {
                "name": member["name"],
                "address": f"0x{addr:X}",
                "size": member["bits"],
                "source": f"CMSIS {path.name}",
            }
            if member.get("access"):
                entry["access"] = member["access"]

            # 交叉验证二：这个地址在 SVD 里存不存在、叫什么
            svd_name = svd_by_addr.get(addr)
            if svd_name is None:
                address_not_in_svd.append(
                    f"{instance}.{member['name']} @0x{addr:X}")
                if existing is not None:
                    # SVD 有同名组但不认这个地址 → 多半是共用结构体的多余
                    # 字段，不收。事实照记，不静默。
                    unmodeled_by_svd.append(
                        f"{instance}.{member['name']} @0x{addr:X}")
                    continue
            elif not svd_name.startswith(f"{instance}."):
                svd_name_notes.append(
                    f"{instance}.{member['name']} ← SVD 写作 {svd_name}")

            if existing is not None:
                have_keys = {(r.get("name"), r.get("address"))
                             for r in existing.get("registers", [])}
                if (entry["name"], entry["address"]) in have_keys:
                    continue        # SVD 已有同名同址，不重复
                aliases += 1
            else:
                n_regs += 1
            regs.append(entry)

        if not regs:
            continue
        if existing is not None:
            # 合并：SVD 原寄存器全部保留，后面追加器件头的同址别名。
            # **不就地改 `existing`** —— 它可能被调用方持有，原地 append
            # 会让「生成一次」变成「生成 N 次、越跑越多」的幽灵 bug。
            merged = dict(existing)
            merged["registers"] = list(existing.get("registers", [])) + regs
            merged["description"] = (
                f"{existing.get('description', '')}；追加 {path.name} 的同址别名")
            groups[instance] = merged
            merged_into_svd += 1
        else:
            groups[instance] = {
                "description": (f"CMSIS 器件头实例 {instance} "
                                f"({type_name}, base 0x{base:X})"),
                "registers": regs,
            }

    info = {
        "parser_version": PARSER_VERSION,
        "source_file": path.name,
        "counts": {"peripherals": len(groups), "registers": n_regs,
                   "aliases_merged": aliases},
        "problems": problems,
        "merged_into_svd_groups": merged_into_svd,
        "offset_conflicts": offset_conflicts[:80],
        "base_offset_notes": base_offset_notes[:40],
        "svd_name_differences": svd_name_notes[:120],
        "address_not_in_svd": address_not_in_svd[:120],
        "not_modeled_by_svd": unmodeled_by_svd[:120],
    }
    return groups, info


def default_device_header(mcu: str = "stm32h743zit6") -> Path | None:
    """本机默认器件头（B 区 packages，随 `ff setup` 安装）；找不到返回 None。"""
    from firmforge.knowledge.parity import STM32_DEVICES, default_cmsis_include

    entry = STM32_DEVICES.get(mcu)
    if not entry:
        return None
    return default_cmsis_include() / entry[1]


def static_assert_source(
    device_header: Path | str,
    *,
    types: Iterable[str] | None = None,
) -> str:
    """生成 `_Static_assert(offsetof(...))` 源，交 arm-none-eabi-gcc 判卷。

    与 `cmsis_core.static_assert_source` 同一思路，区别在类型来源：这里取
    「在器件头里有指针宏的 `*_TypeDef`」—— 也就是源码真正会碰到的那些。
    实测 H743：66 个类型 / 936 条断言 / gcc rc=0。

    为什么必须多这一步：结构体累加偏移与厂商注释偏移都是推理，`offsetof`
    由编译器给出，是实测。器件头的 `__I` 限定符曾被漏认，正是这一步把
    「DTIMER 之后整体差 0x14」逼了出来 —— 光看注释比对看不出来（差值恒定）。
    """
    path = Path(device_header)
    text = path.read_text(encoding="utf-8", errors="replace")
    structs, _problems = parse_structs(text)
    wanted = set(types) if types is not None else {
        t for _instance, t, _base in parse_instances(text)}

    names: set[str] = set()
    for type_name in wanted:
        for member in structs.get(type_name, []):
            if not member["name"].startswith("RESERVED"):
                names.add(member["name"])

    lines = [
        "/* 由 cmsis_instances.static_assert_source() 生成 —— "
        "验证器件头外设寄存器偏移 */",
        f'#include "{path.name}"',
        "#include <stddef.h>",
        "",
        "/* 成员名可能与厂商宏同名（`COMP1` 既是结构体成员又是外设指针宏），",
        " * 不先 #undef 就会被宏展开成 `((COMP_TypeDef *) ...)`，offsetof",
        " * 直接语法错误。这不是算错，是验证脚本要自己躲开的坑。 */",
    ]
    for name in sorted(names):
        lines += [f"#ifdef {name}", f"#undef {name}", "#endif"]

    for type_name in sorted(wanted):
        members = structs.get(type_name)
        if not members:
            continue
        lines += ["", f"/* {type_name} */"]
        for member in members:
            if member["name"].startswith("RESERVED"):
                continue
            lines.append(
                f'_Static_assert(offsetof({type_name}, {member["name"]}) '
                f'== 0x{member["offset"]:X}, "{type_name}.{member["name"]}");')
    return "\n".join(lines) + "\n"


__all__ = ["PARSER_VERSION", "parse_instances", "default_device_header",
           "build_instance_groups", "static_assert_source"]
