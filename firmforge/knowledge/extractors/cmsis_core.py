"""CMSIS 内核寄存器（SCB / DWT / CoreDebug / SysTick / NVIC / ITM / MPU / FPU）→ 知识库。

**为什么需要这个模块（2026-10-27 实测）**

SVD 里确实有 `SCB` / `NVIC` / `MPU` / `FPU` 四个内核外设，但**寄存器名是
SVD 自己的写法**，与源码里写的不是一回事：

| 源码里写的 | SVD / 知识库里的 |
|:--|:--|
| `SCB->CFSR`  | `CFSR_UFSR_BFSR_MMFSR` |
| `SCB->SHCSR` | `SHCRS`（SVD 自己的拼写错误） |

器件头对齐救不了这一类：内核寄存器不在 `stm32h743xx.h` 里，它们在
`core_cm7.h`，而生成器的对齐步骤只读器件头。于是
`lookup_register_qualified("SCB", "CFSR")` 查不到 → 判成"幻觉寄存器"
→ error → 源审查 FAIL → 置信度被硬压到 30%。

同时 `DWT` / `CoreDebug` / `SysTick` / `ITM` / `TPIU` **整个不在 SVD 里**。
任何用异常栈帧（`SCB->CFSR`）或周期计时（`DWT->CYCCNT`）的固件都必踩，
而这两样恰好是崩溃转储与周期测量的标准做法。

**做法：以 `core_cm7.h` 为准，SVD 只做交叉验证**

`core_cm7.h` 是 ARM 官方发布的 CMSIS 头，源码里写的就是它的结构体成员名。
三样东西分别取：

1. **寄存器名 + 偏移** ← `typedef struct {...} SCB_Type;` 的成员顺序与类型；
2. **外设基址** ← `#define SCB_BASE (SCS_BASE + 0x0D00UL)`；
3. **位域名 + 位号 + 位宽** ← `#define SCB_CFSR_IBUSERR_Pos 0U` / `_Msk`。

两处交叉验证（都不是孤证）：

* 头文件里每个成员后面带 `/*!< Offset: 0xNNN */` 注释 —— 那是 ARM 生成
  文档时算出来的偏移，与"按 C 结构体布局累加"是两种独立算法，不一致就报出来；
* SVD 里同地址的寄存器用来补 `svd_name`，从而把 `SHCRS` 这种拼写差异留痕，
  而不是静默选一边。

**为什么能信"按结构体累加"**：这些结构体里没有真正的位域（bit field），
全部是 `uint8_t/uint16_t/uint32_t` 与定长数组，C 的布局规则是确定的。
唯一的匿名 union（ITM 的 32 个激励端口）按 sizeof 最大成员 = 4 字节处理。
`static_assert_source()` 会把这些偏移写成 `_Static_assert(offsetof(...))`
交给 arm-none-eabi-gcc 现场判卷 —— 编译器说了算。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

#: 生成器版本 —— 参与 lock.json 失效判定。改提取逻辑必须递增。
PARSER_VERSION = "cmsis-core/1.0.0"

#: 期望覆盖的内核外设组。**只用于"缺了哪个"的报告**，实际分组由头文件里的
#: 指针宏 `#define SCB ((SCB_Type *) SCB_BASE)` 决定 —— 靠这张表去拼基址
#: 宏名会错：`TPI_Type` 的基址宏叫 `TPI_BASE`、`SCnSCB` 干脆直接用 `SCS_BASE`。
EXPECTED_GROUPS = (
    "SCB", "NVIC", "SysTick", "ITM", "DWT", "TPI", "MPU", "FPU",
    "CoreDebug", "SCnSCB",
)

#: 外设指针宏：`#define SCB ((SCB_Type *) SCB_BASE)`
#: 这一行同时给出**组名**、**结构体类型**和**基址来源**，是三样东西的
#: 唯一权威出处，比"猜某张表里的宏名"可靠得多。
_PERIPH_MACRO_RE = re.compile(
    r"^[ \t]*#[ \t]*define[ \t]+([A-Za-z_]\w*)[ \t]+"
    r"\(\([ \t]*([A-Za-z_]\w*)[ \t]*\*[ \t]*\)[ \t]*([A-Za-z_]\w*)[ \t]*\)",
    re.M)

#: 成员声明：`__IOM uint32_t SHCSR;` / `uint32_t RESERVED0[1U];` / `__IM uint8_t SHPR[12U];`
_MEMBER_RE = re.compile(
    r"^\s*(?:(__IM|__IOM|__OM)\s+)?"
    r"(uint8_t|uint16_t|uint32_t|int8_t|int16_t|int32_t)\s+"
    r"([A-Za-z_]\w*)\s*"
    r"(?:\[\s*(\w+)\s*\])?\s*;")

#: 成员行尾的偏移注释：`/*!< Offset: 0x028 (R/W)  Configurable Fault Status Register */`
_OFFSET_COMMENT_RE = re.compile(r"Offset:\s*0x([0-9A-Fa-f]+)")

_ACCESS_FROM_QUALIFIER = {"__IM": "ro", "__IOM": "rw", "__OM": "wo"}

#: 位域宏：`#define SCB_CFSR_IBUSERR_Pos 0U`
#: 注意取值可能是**表达式**：`#define SCB_CFSR_MMARVALID_Pos (SCB_CFSR_MEMFAULTSR_Pos + 7U)`
_FIELD_POS_RE = re.compile(r"^#define\s+([A-Za-z_]\w*)_Pos\s+(.+?)\s*(?:/\*.*)?$")

#: 位宽用 `_Msk` 里那个常量的位长推出：`(0xFFUL << ...)` → 8；`1UL` → 1
_FIELD_MSK_RE = re.compile(r"^#define\s+([A-Za-z_]\w*)_Msk\s+\(?\s*(0x[0-9A-Fa-f]+|\d+)[ULul]*")

#: 基址宏：`#define SCB_BASE (SCS_BASE + 0x0D00UL)` / `(0xE000E000UL)`
#: 注意 `re.MULTILINE`：整份头文件按全文匹配时，`^` 默认只认字符串开头；
#: 还要容忍前导空白 —— `  #define MPU_BASE ...` 是写在外层 #if 里的缩进形态。
_BASE_RE = re.compile(r"^[ \t]*#[ \t]*define[ \t]+([A-Za-z_]\w*_BASE)[ \t]+\(([^)]*)\)",
                      re.M)

_TYPES = {"uint8_t": 8, "uint16_t": 16, "uint32_t": 32,
          "int8_t": 8, "int16_t": 16, "int32_t": 32}


def _eval_base(expr: str, known: dict[str, int]) -> int | None:
    """求值 `SCS_BASE + 0x0D00UL` 这种简单表达式。

    只支持 `+` 与常量 —— CMSIS 的基址宏就这两种形态。**读不出就返回 None**，
    不猜默认值（猜错等于把地址写进库里，后果比缺失严重得多）。
    """
    total = 0
    for term in expr.replace("(", " ").replace(")", " ").split("+"):
        term = term.strip().rstrip("ULul").strip()
        if not term:
            continue
        if term in known:
            total += known[term]
        elif re.fullmatch(r"0[xX][0-9A-Fa-f]+|\d+", term):
            total += int(term, 0)
        else:
            return None
    return total


def parse_base_addresses(text: str) -> dict[str, int]:
    """解析全部 `*_BASE` 宏（含相互引用，按可解析轮次迭代）。"""
    pending = dict(_BASE_RE.findall(text))
    known: dict[str, int] = {}
    for _ in range(5):                      # 依赖链最长 2 层，5 轮足够
        progressed = False
        for name, expr in list(pending.items()):
            value = _eval_base(expr, known)
            if value is not None:
                known[name] = value
                pending.pop(name)
                progressed = True
        if not progressed:
            break
    return known


def parse_structs(text: str) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
    """解析 `typedef struct {...} XXX_Type;`，返回 (类型名 → 成员表, 问题表)。

    成员表每项：`{name, offset, bits, access, count, comment_offset}`。
    `comment_offset` 是头文件注释里的偏移，用于和累加结果交叉验证。
    """
    structs: dict[str, list[dict[str, Any]]] = {}
    problems: list[str] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        if not re.match(r"^\s*typedef\s+struct\s*$", lines[i]) and \
                not re.match(r"^\s*typedef\s+struct\s*\{", lines[i]):
            i += 1
            continue
        members: list[dict[str, Any]] = []
        offset_bits = 0
        i += 1
        closed: str | None = None
        while i < len(lines):
            line = lines[i]
            end = re.match(r"^\s*\}\s*([A-Za-z_]\w*)\s*;", line)
            if end:
                closed = end.group(1)
                break

            # 匿名 union（ITM 的 32 个激励端口）：按 sizeof 最大成员处理
            if re.search(r"\bunion\b", line) and "}" not in line:
                union_name = ""
                union_count = 1
                union_comment = 0
                # `__OM  union` 这一行没有 `{`，左花括号在下一行 ——
                # 所以深度不能从 1 起算，也不能假设两行形状固定：
                # 先等第一个 `{` 出现（opened），再等它归零。
                # 差这一层会让扫描冲出结构体、一路吃到文件尾，
                # 结果是 ITM 的成员被算进了 DWT（实测偏移整体差 4 字节）。
                depth = 0
                opened = False
                i += 1
                while i < len(lines):
                    inner = lines[i]
                    depth += inner.count("{")
                    depth -= inner.count("}")
                    if depth > 0:
                        opened = True
                    elif opened:
                        tail = re.match(
                            r"^\s*\}\s*([A-Za-z_]\w*)\s*(?:\[\s*(\w+)\s*\])?\s*;",
                            inner)
                        if tail:
                            union_name = tail.group(1)
                            count_raw = (tail.group(2) or "").strip().rstrip("Uu")
                            union_count = int(count_raw) if count_raw.isdigit() else 1
                            found = _OFFSET_COMMENT_RE.search(inner)
                            union_comment = int(found.group(1), 16) if found else 0
                        break
                    i += 1
                if union_name:
                    members.append({
                        "name": union_name, "offset": offset_bits // 8,
                        "bits": 32, "access": "", "count": union_count,
                        "comment_offset": union_comment, "union": True,
                    })
                    offset_bits += 32 * union_count
                else:
                    problems.append("union 成员解析失败（结构体内匿名联合）")
                i += 1
                continue

            m = _MEMBER_RE.match(line)
            if m:
                qualifier, ctype, name, count_raw = m.groups()
                bits = _TYPES[ctype]
                count = 1
                if count_raw:
                    raw = count_raw.rstrip("Uu")
                    if raw.isdigit():
                        count = int(raw)
                    else:
                        problems.append(f"{name}: 数组长度不是常量（{count_raw}）")
                found = _OFFSET_COMMENT_RE.search(line)
                members.append({
                    "name": name,
                    "offset": offset_bits // 8,
                    "bits": bits,
                    "access": _ACCESS_FROM_QUALIFIER.get(qualifier or "", ""),
                    "count": count,
                    "comment_offset": int(found.group(1), 16) if found else None,
                })
                offset_bits += bits * count
            i += 1
        if closed:
            structs[closed] = members
        i += 1
    return structs, problems


def parse_field_macros(text: str) -> list[dict[str, Any]]:
    """解析 `*_Pos` / `*_Msk` 宏 → `[{base, bit, bit_width}]`。

    `base` 是**去掉 `_Pos` 的完整宏名**，也就是源码里真正出现的写法
    （`SCB_CFSR_IBUSERR`）。位宽由 `_Msk` 的常量位长推出。

    `_Pos` 的取值可能是表达式而不是常量 —— CMSIS 里 `CFSR` 的分段位就是这么
    写的：`#define SCB_CFSR_MMARVALID_Pos (SCB_CFSR_MEMFAULTSR_Pos + 7U)`。
    只认十进制字面量会把 CFSR 的 24 个真实位域全丢掉（只剩 3 个分段别名），
    而这 24 个才是崩溃转储要看的东西。所以这里按"名字 + 偏移"递归求值，
    求不出就记 `unresolved`，**不猜**。
    """
    raw: dict[str, str] = {}
    for line in text.splitlines():
        m = _FIELD_POS_RE.match(line.strip())
        if m:
            raw[m.group(1)] = m.group(2).strip()

    widths: dict[str, int] = {}
    for line in text.splitlines():
        m = _FIELD_MSK_RE.match(line.strip())
        if not m:
            continue
        try:
            value = int(m.group(2), 0)
        except ValueError:
            continue
        widths[m.group(1)] = max(1, value.bit_length())

    resolved: dict[str, int] = {}
    for _ in range(6):                       # 依赖链实测最长 2 层，6 轮足够
        progressed = False
        for name, expr in raw.items():
            if name in resolved:
                continue
            value = _eval_pos(expr, resolved)
            if value is not None:
                resolved[name] = value
                progressed = True
        if not progressed:
            break

    out: list[dict[str, Any]] = []
    for name, expr in raw.items():           # 保持头文件里的原始顺序
        if name not in resolved:
            out.append({"base": name, "bit": None, "bit_width": 1,
                        "unresolved": expr})
            continue
        out.append({"base": name, "bit": resolved[name],
                    "bit_width": widths.get(name, 1)})
    return out


def _eval_pos(expr: str, known: dict[str, int]) -> int | None:
    """求值 `(SCB_CFSR_MEMFAULTSR_Pos + 7U)` 这类 `_Pos` 表达式。

    允许的形态只有 `常量` 与 `名字 + 常量` 的加法链（CMSIS 全篇如此）。
    出现别的运算符就返回 None —— 宁可漏一条，也不给一个算错的位号。
    """
    body = re.sub(r"/\*.*?\*/", " ", expr)
    body = body.strip().strip("()")
    total = 0
    for term in body.split("+"):
        term = term.strip().strip("()").strip().rstrip("ULul")
        if not term:
            continue
        if re.fullmatch(r"0[xX][0-9A-Fa-f]+|\d+", term):
            total += int(term, 0)
            continue
        if term.endswith("_Pos"):
            key = term[:-4]
            if key in known:
                total += known[key]
                continue
        return None
    return total


def parse_peripheral_macros(text: str) -> list[tuple[str, str, str]]:
    """解析 `#define SCB ((SCB_Type *) SCB_BASE)` → `[(组名, 类型, 基址宏)]`。

    这比维护一张"组名 → 基址宏名"的表可靠：`TPI` 用 `TPI_BASE`、
    `SCnSCB` 直接用 `SCS_BASE`、`MPU` 写在 `#if __MPU_PRESENT` 里带缩进 ——
    三种形态都能从宏本身读出来，而表一定会漏。
    """
    out: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for name, type_name, base in _PERIPH_MACRO_RE.findall(text):
        if not type_name.endswith("_Type") or name in seen:
            continue
        seen.add(name)
        out.append((name, type_name, base))
    return out


def build_core_groups(core_header: Path | str,
                      svd_groups: dict[str, Any] | None = None
                      ) -> tuple[dict[str, Any], dict[str, Any]]:
    """产出内核外设的 `register_groups` 片段 + 统计/问题。

    Args:
        core_header: `core_cm7.h`（CMSIS Core，ARM 官方）。
        svd_groups: 已生成的 SVD 分组（可选）。用来补 `svd_name` 并把
            "SVD 与 CMSIS 名字不一致"这件事留痕，而不是静默选一边。

    Returns:
        `(groups, info)`。`info` 含 counts 与 problems，供 `_generator` 落盘。
    """
    header = Path(core_header)
    text = header.read_text(encoding="utf-8", errors="replace")
    bases = parse_base_addresses(text)
    structs, struct_problems = parse_structs(text)
    fields = parse_field_macros(text)
    peripherals = parse_peripheral_macros(text)

    problems: list[str] = list(struct_problems)
    groups: dict[str, Any] = {}
    n_regs = n_fields = 0
    offset_conflicts: list[str] = []
    svd_name_notes: list[str] = []
    unresolved_fields: list[str] = []

    svd_groups = svd_groups or {}
    for field in fields:
        if field.get("bit") is None:
            unresolved_fields.append(
                f"{field['base']}: {field.get('unresolved', '')}")

    found_groups: set[str] = set()
    for group, type_name, base_macro in peripherals:
        members = structs.get(type_name)
        if not members:
            problems.append(f"{group}: 头文件里没有 {type_name}（跳过）")
            continue
        base = bases.get(base_macro)
        if base is None:
            problems.append(f"{group}: 未解析出 {base_macro}（跳过）")
            continue
        found_groups.add(group)

        # -- SVD 交叉验证：同地址寄存器名 / 位域描述 -------------------
        svd_by_offset: dict[int, dict[str, Any]] = {}
        for reg in (svd_groups.get(group) or {}).get("registers", []):
            try:
                svd_by_offset[int(reg["address"], 16) - base] = reg
            except (KeyError, ValueError):
                continue

        regs: list[dict[str, Any]] = []
        for member in members:
            if member["name"].startswith("RESERVED"):
                continue
            addr = base + member["offset"]
            # 交叉验证：注释写的偏移必须与按 C 布局累加的一致
            comment = member.get("comment_offset")
            if comment is not None and comment != member["offset"]:
                offset_conflicts.append(
                    f"{group}.{member['name']}: 结构体累加 0x{member['offset']:X} "
                    f"≠ 注释 0x{comment:X}")

            entry: dict[str, Any] = {
                "name": member["name"],
                "address": f"0x{addr:X}",
                "size": member["bits"],
                "source": f"CMSIS Core {header.name}",
            }
            if member["access"]:
                entry["access"] = member["access"]

            svd_reg = svd_by_offset.get(member["offset"])
            if svd_reg and svd_reg.get("name") != member["name"]:
                # **不写 `address_source`**：schema 里那个字段的语义是
                # 「经裁定表修正后取的是 SVD 还是器件头」，二值枚举。
                # 这里不是修正、是换来源，往里塞自由文本会直接违反 schema。
                # 名字差异已有专门的去处（`info["svd_name_differences"]`），
                # 而地址来源看 `source` 字段本身就是了。
                svd_name_notes.append(
                    f"{group}.{member['name']} ← SVD 写作 {svd_reg['name']}")

            # -- 位域：按 `<组>_<寄存器>_` 前缀从宏里取 ------------------
            prefix = f"{group}_{member['name']}_"
            group_fields: list[dict[str, Any]] = []
            for field in fields:
                if field.get("bit") is None:
                    continue
                if not field["base"].startswith(prefix):
                    continue
                bit = field["bit"]
                # 数组型寄存器（ISER[8] / PORT[32]）的位域宏按第 0 个元素命名，
                # 位号落在单寄存器宽度内，直接收；超出说明宏描述的是别的语义。
                if bit >= max(member["bits"], 32):
                    continue
                item: dict[str, Any] = {
                    "name": field["base"],
                    "bit": bit,
                    "bit_width": field["bit_width"],
                    "name_source": "cmsis_macro",
                }
                if svd_reg:
                    for sf in svd_reg.get("fields", []):
                        if sf.get("bit") == bit:
                            if sf.get("name") != field["base"]:
                                item["svd_name"] = sf["name"]
                            if sf.get("description"):
                                item["description"] = sf["description"]
                            break
                group_fields.append(item)
            if group_fields:
                group_fields.sort(key=lambda f: f["bit"])
                entry["fields"] = group_fields
                n_fields += len(group_fields)

            regs.append(entry)
            n_regs += 1

        if regs:
            groups[group] = {
                "description": (f"CMSIS 内核外设 {group} "
                                f"({type_name}, base 0x{base:X})"),
                "registers": regs,
            }

    for expected in EXPECTED_GROUPS:
        if expected not in found_groups:
            problems.append(f"{expected}: 头文件里没有对应的外设指针宏（未收录）")

    info = {
        "parser_version": PARSER_VERSION,
        "source_file": header.name,
        "counts": {"peripherals": len(groups), "registers": n_regs,
                   "fields": n_fields},
        "problems": problems,
        "offset_conflicts": offset_conflicts,
        "svd_name_differences": svd_name_notes,
        "unresolved_fields": unresolved_fields,
    }
    return groups, info


# ---------------------------------------------------------------------------
# 独立验证：让编译器给偏移判卷
# ---------------------------------------------------------------------------

def static_assert_source(core_header: Path | str) -> str:
    """生成一份 `_Static_assert(offsetof(...))` 的 C 源。

    为什么必须多这一步：上面算偏移靠"按 C 布局累加"，注释偏移是 ARM 生成
    文档时算的 —— 两者都是推理。`offsetof` 由编译器给出，是**实测**。
    把这份源交给 arm-none-eabi-gcc 编一次，偏移就再也不是"我算的"。
    """
    header = Path(core_header)
    text = header.read_text(encoding="utf-8", errors="replace")
    structs, _ = parse_structs(text)
    pairs: list[tuple[str, str, int]] = []          # (组, 类型, 成员, 偏移)
    names: set[str] = set()
    for group, type_name, _base in parse_peripheral_macros(text):
        for member in structs.get(type_name, []):
            if member["name"].startswith("RESERVED"):
                continue
            pairs.append((group, type_name, member["name"], member["offset"]))
            names.add(member["name"])

    lines = [
        "/* 由 cmsis_core.static_assert_source() 生成 —— 验证内核寄存器偏移 */",
        '#include "stm32h743xx.h"',
        "#include <stddef.h>",
        "",
        "/* 成员名必须躲开厂商宏：DWT 的 COMP1/COMP2 与 stm32h743xx.h 里的",
        " * COMP1/COMP2（比较器外设指针）同名，不 #undef 就会被宏展开成",
        " * ((COMP_TypeDef *) ...)，offsetof 直接语法错误。这不是我们算错，",
        " * 而是「库名与器件宏同名」这个老坑在验证脚本里的又一次现身。 */",
    ]
    for name in sorted(names):
        lines.append(f"#ifdef {name}")
        lines.append(f"#undef {name}")
        lines.append("#endif")
    lines.append("")
    for group, type_name, member_name, offset in pairs:
        lines.append(
            f'_Static_assert(offsetof({type_name}, {member_name}) '
            f'== 0x{offset:X}, "{group}.{member_name}");')
    return "\n".join(lines) + "\n"


__all__ = [
    "PARSER_VERSION", "EXPECTED_GROUPS", "parse_base_addresses",
    "parse_structs", "parse_field_macros", "parse_peripheral_macros",
    "build_core_groups", "static_assert_source", "default_core_header",
]


def default_core_header(name: str = "core_cm7.h") -> Path | None:
    """本机 ARM CMSIS Core 头文件（B 区 packages，取最高版本）。

    路径形如 `packages/stm32/cmsis_5/<ver>/CMSIS/Core/Include/core_cm7.h`。
    版本目录按**数值**排序取最新的一个 —— 字符串序会把 `5.10.0` 排在
    `5.9.0` 前面，那样升级一次反而取到旧头。

    找不到返回 None（不抛）：生成器在缺件时的正确行为是「跳过并报出来」，
    由调用方决定提示文案，而不是让 import 期炸掉整条流水线。
    """
    from firmforge.infrastructure import paths
    root = paths.packages_dir() / "stm32" / "cmsis_5"
    if not root.is_dir():
        return None
    cands = [p for p in root.glob(f"*/CMSIS/Core/Include/{name}") if p.is_file()]
    if not cands:
        return None

    def _vkey(path: Path) -> tuple[int, ...]:
        ver = path.parents[3].name
        parts: list[int] = []
        for chunk in re.split(r"[.\-_]", ver):
            digits = re.match(r"\d+", chunk)
            parts.append(int(digits.group()) if digits else 0)
        return tuple(parts)

    return sorted(cands, key=_vkey)[-1]
