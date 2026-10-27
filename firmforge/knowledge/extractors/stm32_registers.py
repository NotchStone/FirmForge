"""CMSIS-SVD → STM32 寄存器骨架提取器。

原料
----
芯片厂商发布的 CMSIS-SVD：`http://cmsis-svd.github.io/.../data/STMicro/STM32H743x.svd`
（本机走 `api.github.com` 的 raw 头下载，见 `docs/STM32-工具链选型.md`）。

SVD 是**厂商自己的机器可读描述**，不是第三方转录 —— 这是它比"抄数据手册"
更可靠的地方。但它**也不能当孤证**（见下「为什么必须交叉验证」）。

与 AVR 路线的根本差异
---------------------
AVR 那份器件头是「宏 + 地址」，寄存器与位域是**同一个命名空间里的宏**，
所以要用 `avr-gcc -dD` 求值。SVD 是**结构化的 XML**：外设 / 寄存器 / 位域
三层嵌套，各自是裸名，属性全部显式——不需要预处理器，也不需要猜「谁挨着谁」。

于是省掉了 AVR 那套两层解析，但换来两类 SVD 特有的活：

1. **derivedFrom 继承**。本机 128 个外设里 51 个是派生的
   （GPIOB..GPIOK 挂着 GPIOA、USART2/3 挂着 USART1、TIM3..5 挂着 TIM2…）。
   不展开就只剩 1998 条，展开后 2955 条 —— 少掉 957 条（32%）。
2. **属性归一化**。SVD 的 `<size>` 写成 **十六进制**（`0x20` = 32 位，
   本机 1794 条这么写），`<access>` 是 `read-write` 这种**全称**
   （AVR 那份 schema 用的是 `rw`/`ro`/`wo` 缩写）。不归一化就直接违反 schema。

产出形态：为什么直接沿用 `register_groups`
------------------------------------------
AVR 的骨架把寄存器全塞进 `"unclassified"`（生成器**不猜**功能分组）。
STM32 不用猜 —— SVD 的 `<peripheral>` 就是权威分组，所以分组 key 直接用
外设实例名（`GPIOA` / `RCC` / `USART1`）。

寄存器条目存**裸名**（`MODER`，不是 `GPIOA.MODER`）。理由见
`.workbuddy/memory/MEMORY-REFERENCE.md` §六：SVD 规范自己就把限定名当
**渲染期行为**（`prependToName` / `appendToName`），不是存储格式；且
`GPIOA_MODER` 这种下划线拼法会与 CMSIS 的「组名前缀宏」撞车、且不可逆。

需要扁平键时按 `外设.寄存器` 现拼（点号在 C 标识符里非法，天然与源码
token 隔离）—— 由 `qualified_name()` 提供，不在数据里落地。

为什么必须交叉验证
------------------
本机实测：`STM32H742x.svd` 与 `STM32H743x.svd` **逐字节只差 2 个字节**
（`742`↔`743`），寄存器结构一字不差 —— 但 H742 实际**不含**
Ethernet MAC / USB OTG HS / JPEG。

**这不是「同 die」的证据，是 ST 的数据缺陷。** 所以生成器只负责产数据，
「对不对」由 `stm32_devheader`（器件头）做第二来源比对 —— 见
`firmforge/knowledge/parity.py` 的 `compare_stm32()`。

生成时用器件头做什么
--------------------
SVD 给**结构**（哪个寄存器在哪个地址、有哪些位），器件头给**名字与位号的
最终裁决**：源码里出现的是 `GPIO_MODER_MODER0_Pos`，不是 SVD 的 `MODE0`。
两边名字对上的，数据里存宏基名（`GPIO_MODER_MODER0`），SVD 名留 `svd_name`；
位号不一致的按 `parity.STM32_KNOWN_ISSUES` 裁定，未裁定的打 `bit_conflict`
标记 —— **不静默选一边**（静默选错等于把缺陷藏进数据里）。
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import firmforge.knowledge.extractors.cmsis_core as core
import firmforge.knowledge.extractors.stm32_devheader as dev

#: 生成器版本 —— 参与 lock.json 的失效判定。
#: **改提取逻辑必须递增它**，否则「改了规则但缓存没失效」会变成幽灵 bug。
#: 1.1.0：并入 CMSIS 内核块（SCB / DWT / CoreDebug …），见 `cmsis_core`。
EXTRACTOR_VERSION = "stm32-registers/1.1.0"

#: SVD 的 access 全称 → 项目 schema 的缩写。
#: 后两条是规范允许但本机未出现的取值，一并登记免得日后静默变成 None。
_ACCESS_MAP: dict[str, str] = {
    "read-only": "ro",
    "read-write": "rw",
    "write-only": "wo",
    "read-writeOnce": "rw",
    "writeOnce": "wo",
}


def _text(node: ET.Element, tag: str) -> str:
    """取子元素文本并清洗空白（SVD 里 description 常带换行缩进）。"""
    found = node.find(tag)
    return (found.text or "").strip() if found is not None else ""


def _int(node: ET.Element, tag: str) -> int | None:
    """取整数值。**必须 `int(s, 0)`** —— SVD 把 `<size>` 写成 `0x20`。

    直接用 `int(s)` 会在这 1794 条上抛 ValueError。返回 None 表示无此元素。
    """
    raw = _text(node, tag)
    if not raw:
        return None
    try:
        return int(raw, 0)
    except ValueError:
        return None


# --------------------------------------------------------------------------
# 继承展开
# --------------------------------------------------------------------------


def _resolve_derived_from(node: ET.Element, own_name: str) -> str:
    """`derivedFrom` 属性 → 实际被继承的外设名。

    规范允许 `%s` 通配（派生者用自己的名字替换）。本机 128 个外设的
    `derivedFrom` 全是裸名，但带 `%s` 的 SVD 是合法的，处理掉免得日后踩。
    """
    raw = (node.get("derivedFrom") or "").strip()
    if not raw:
        return ""
    return raw.replace("%s", own_name) if "%s" in raw else raw


def _resolve_group_name(node: ET.Element, by_name: dict[str, ET.Element],
                        seen: frozenset[str] = frozenset()) -> str:
    """`groupName` 沿 `derivedFrom` 向上找。

    **`groupName` 也是可继承元素** —— 本机 128 个外设里有 51 个的
    `groupName` 为空（GPIOB..GPIOK 挂 GPIOA、I2C2..I2C4 挂 I2C1…），
    派生者自己不写，值在基外设上。不沿链找就会让这 51 个拿到空串，
    而 groupName 正是「限定名/宏前缀」的来源（`GPIO_MODER_*` 的 `GPIO`）。
    """
    name = _text(node, "name")
    if name in seen:
        return ""
    own = _text(node, "groupName")
    if own:
        return own
    base = _resolve_derived_from(node, name)
    if base and base in by_name:
        return _resolve_group_name(by_name[base], by_name, seen | {name})
    return ""


def _collect_registers(per: ET.Element, by_name: dict[str, ET.Element],
                       seen: frozenset[str] = frozenset()) -> list[ET.Element]:
    """收集一个外设的寄存器，沿 `derivedFrom` 向上继承。

    SVD 继承语义是**全量继承**（派生者通常不带 `<registers>`），
    子自己的同名寄存器覆盖父的 —— 实测本机只有一层继承，但按规范写的
    递归能兼容更深的链。
    """
    name = _text(per, "name")
    own = list(per.findall("./registers/register"))

    base = _resolve_derived_from(per, name)
    inherited: list[ET.Element] = []
    if base and base in by_name and base not in seen:
        inherited = _collect_registers(by_name[base], by_name, seen | {name})

    if not inherited:
        return own

    own_names = {_text(r, "name") for r in own}
    return own + [r for r in inherited if _text(r, "name") not in own_names]


# --------------------------------------------------------------------------
# 解析
# --------------------------------------------------------------------------


def _parse_register(node: ET.Element) -> dict[str, Any] | None:
    """SVD `<register>` → 项目 schema 的 register 条目（不含分组与地址）。

    返回 None 表示这条缺关键字段（没有名字或偏移），由调用方计数。
    """
    name = _text(node, "name")
    offset = _int(node, "addressOffset")
    if not name or offset is None:
        return None

    out: dict[str, Any] = {
        "name": name,
        "offset": offset,                      # 由调用方折算成绝对地址
        "size": _int(node, "size") or 32,      # STM32 默认 32 位
    }

    access = _ACCESS_MAP.get(_text(node, "access"))
    if access:
        out["access"] = access

    reset = _int(node, "resetValue")
    if reset is not None:
        out["reset"] = reset

    fields: list[dict[str, Any]] = []
    skipped = 0
    for fnode in node.findall("./fields/field"):
        fname = _text(fnode, "name")
        bit = _int(fnode, "bitOffset")
        if not fname or bit is None:
            skipped += 1
            continue
        field: dict[str, Any] = {"name": fname, "bit": bit}
        width = _int(fnode, "bitWidth")
        if width is not None and width != 1:
            # 单比特位域不写 bit_width —— 与 AVR 数据同形，省 7789 个冗余字段
            field["bit_width"] = width
        faccess = _ACCESS_MAP.get(_text(fnode, "access"))
        if faccess:
            field["access"] = faccess
        fields.append(field)

    if fields:
        fields.sort(key=lambda f: f["bit"])
        out["fields"] = fields
    if skipped:
        out["_skipped_fields"] = skipped
    return out


def parse_svd(svd_path: Path | str) -> dict[str, Any]:
    """解析 SVD，返回 ``{"device", "version", "peripherals": [...]}``。

    每个外设形如::

        {"name": "GPIOA", "base_address": 0x58020000, "group_name": "GPIO",
         "registers": [{"name","offset","size","access","reset","fields"}, ...]}
    """
    root = ET.parse(str(svd_path)).getroot()

    per_nodes = list(root.findall("./peripherals/peripheral"))
    by_name = {_text(p, "name"): p for p in per_nodes}

    peripherals: list[dict[str, Any]] = []
    for per in per_nodes:
        base = _int(per, "baseAddress")
        if base is None:
            continue
        regs: list[dict[str, Any]] = []
        for rnode in _collect_registers(per, by_name):
            reg = _parse_register(rnode)
            if reg is not None:
                regs.append(reg)
        regs.sort(key=lambda r: r["offset"])
        peripherals.append({
            "name": _text(per, "name"),
            "base_address": base,
            "group_name": _resolve_group_name(per, by_name),
            "registers": regs,
        })

    peripherals.sort(key=lambda p: p["name"])
    return {
        "device": _text(root, "name"),
        "version": _text(root, "version"),
        "peripherals": peripherals,
    }


def qualified_name(peripheral: str, register: str,
                   field: str | None = None) -> str:
    """拼扁平限定键 —— `外设.寄存器` / `外设.寄存器.位域`。

    点号在 C 标识符里非法，所以这个键**永远不会**与源码里出现的 token
    撞车（源码里只有 `GPIOA->MODER` 与 `GPIO_MODER_*` 两种写法）。

    下划线拼法被否掉的两个理由：① 不可逆
    （`ADC3_Common_ADC_CCR` 可以切成两种）；② `GPIOA_MODER` 这种串
    看着像 CMSIS 宏但其实不是，对 S2 匹配是干扰。
    """
    if field:
        return f"{peripheral}.{register}.{field}"
    return f"{peripheral}.{register}"


# --------------------------------------------------------------------------
# 第二来源对齐（器件头）
# --------------------------------------------------------------------------


def _pattern_match(pattern: str, value: str) -> bool:
    """一个 `*` 的通配，**位置任意**。

    `AWD*CR` 必须能匹配 `AWD3CR` —— 只支持尾部 `*` 的话，缺陷表里这 3 条
    （ADC1/2/3 的 AWD*CR）全部失效，会给数据打上 3 个假冲突。
    """
    if "*" not in pattern:
        return pattern == value
    head, _, tail = pattern.partition("*")
    return (len(value) >= len(head) + len(tail)
            and value.startswith(head) and value.endswith(tail))


def _known_issues() -> list[Any]:
    """已裁定缺陷表 —— 延迟导入。

    `parity` 顶层会 import `extractors` 包，包又 import 本模块；顶层反向
    import 会成环（拿到的 `STM32_KNOWN_ISSUES` 还没定义）。
    """
    from firmforge.knowledge.parity import STM32_KNOWN_ISSUES
    return STM32_KNOWN_ISSUES


def _structural_peripherals() -> Any:
    """建模粒度与器件头不同的外设（MDMA / DMA / HRTIM …）。

    这些外设的寄存器被器件头拉平或分段，位域名对不上是**结构差异**，
    与「命名口径不一致」要分开计 —— 混在一起会让报告失真。
    """
    from firmforge.knowledge.parity import STRUCTURAL_DIFFERENCES
    return STRUCTURAL_DIFFERENCES


def _adjudicate(known: list[Any], peripheral: str, register: str, kind: str,
                field: str, svd_val: int, hdr_val: int) -> Any | None:
    """通用裁定查询。``kind`` 取 base / offset / bit / bit_shift。

    `bit` 类按**绝对值**对（小整数，稳定），其余按**增量**对
    （`header - svd`）—— 增量才是缺陷本体，绝对地址随芯片变。
    """
    for ki in known:
        if ki.peripheral != peripheral or ki.kind != kind:
            continue
        if not _pattern_match(ki.register, register):
            continue
        if kind == "bit":
            if ki.field and not _pattern_match(ki.field, field):
                continue
            if (svd_val, hdr_val) != (ki.svd_value, ki.header_value):
                continue
        elif hdr_val - svd_val != ki.delta:
            continue
        return ki
    return None


def _adjudicate_bit(known: list[Any], peripheral: str, register: str,
                    field: str, svd_bit: int, header_bit: int) -> Any | None:
    """位号不一致：先按 `bit`（逐字段绝对值）对，再按 `bit_shift`
    （整寄存器平移，BDMA 的 ISR/IFCR 偏 4）兜底。"""
    for kind in ("bit", "bit_shift"):
        ki = _adjudicate(known, peripheral, register, kind, field,
                         svd_bit, header_bit)
        if ki is not None:
            return ki
    return None


def _member_offset(header: Any, struct: str, register: str,
                   peripheral: str, group: str) -> tuple[str | None, int | None]:
    """结构体里找同名成员，返回 ``(成员名, 偏移)``。

    SVD 对部分外设把前缀写进寄存器名（`FDCAN_CCCR`），器件头成员是裸名，
    所以按 `register_name_variants` 逐个试。
    """
    members = header.members(struct)
    for variant in dev.register_name_variants(register, peripheral, group):
        if variant in members:
            return variant, members[variant]
    return None, None


def align_fields_with_header(parsed: dict[str, Any], header: Any, *,
                             known_issues: list[Any] | None = None
                             ) -> dict[str, Any]:
    """把位域名换成**器件头里的宏基名**，位号冲突按裁定表定夺。

    为什么要换名字：SVD 写 `GPIO.MODE0`，源码里出现的是
    `GPIO_MODER_MODER0_Pos`。数据里留 SVD 名，S2 就永远对不上源码 token。
    原名不丢 —— 存进 `svd_name`，用于回溯与两侧口径对照。

    位号不一致时**不静默取一边**：

    =========================  ============================================
    ``bit_source: "header"``   裁定表判 SVD 错 → 取器件头值
    ``bit_source: "svd"``      裁定表判器件头错 → 取 SVD 值
    ``bit_conflict: true``     表里没有 → 保留 SVD 值 + 记 ``header_bit``，
                               并计入 ``bits_conflict``，在交付统计里显形
    =========================  ============================================

    最后一条是兜底：将来若新增未裁定冲突，数据不会静默变「干净」，
    而是带标记出来等人工处理。

    返回对齐统计（写进 ``_generator.header.alignment``）。
    """
    known = _known_issues() if known_issues is None else known_issues
    structural = _structural_peripherals()
    stats: dict[str, Any] = {
        "peripherals_mapped": 0,
        "peripherals_unmapped": [],
        "fields_aligned": 0,
        "fields_renamed": 0,
        # 名字没换成宏基名的三种原因，**必须分开计**：
        #   unmatched   —— 器件头有位域宏、但名字对不上（真问题，要人工看）
        #   structural  —— 该外设建模粒度与器件头不同（预期内，见
        #                  parity.STRUCTURAL_DIFFERENCES）
        #   not_modeled —— 器件头根本没给这个寄存器定义位域宏（覆盖性事实）
        # 合并计会把上万条正常条目报成问题（首跑实测 10157）。
        "fields_unmatched": 0,
        "fields_structural": 0,
        "fields_not_modeled": 0,
        "fields_no_instance": 0,
        "fields_ambiguous": 0,
        # 寄存器地址：SVD 的 13 条缺陷里有多条是「漏保留区 / 偏移写错」，
        # 不修就是 S2 拿错地址比对（PRAR_PRG2 曾整段差 0x100）。
        "registers_corrected": 0,
        "registers_conflict": 0,
        "register_conflicts": [],
        "bits_corrected": 0,
        "bits_conflict": 0,
        "corrections": [],
        "conflicts": [],
    }

    for per in parsed["peripherals"]:
        instance, how = dev.map_peripheral(header, per["name"])
        per["header_instance"] = instance
        per["header_mapping"] = how
        if instance is None:
            stats["peripherals_unmapped"].append(f"{per['name']}({how})")
            # 内核外设 / 器件头无实例：这些位域本来就没有对应的宏，
            # 归「无实例」而不是「命名问题」—— 否则 13 个内核外设会把
            # unmatched 灌成 1500+，把真正要看的那 697 条淹掉。
            stats["fields_no_instance"] += sum(
                len(r.get("fields", ())) for r in per["registers"])
            continue

        stats["peripherals_mapped"] += 1
        is_structural = per["name"] in structural
        hbase = header.base_address(instance)
        struct = header.instances[instance].struct
        for reg in per["registers"]:
            # --- 寄存器地址：按裁定表修正（漏保留区 / 偏移写错） ---------
            if hbase is not None:
                _, moff = _member_offset(header, struct, reg["name"],
                                         per["name"], per["group_name"])
                if moff is not None:
                    svd_abs = per["base_address"] + reg["offset"]
                    # **不加段内偏移**：结构体成员偏移已从器件头外设起点
                    # 算起、天然含段偏移（Ethernet_MTL 的 MTLOMR 在 ETH
                    # 结构体里就是 0xC00）。加了会重复计算，首跑实测把
                    # Ethernet 的 8 个寄存器全报成假冲突。
                    hdr_abs = hbase + moff
                    if hdr_abs != svd_abs:
                        ki = _adjudicate(known, per["name"], reg["name"],
                                         "offset", "", svd_abs, hdr_abs)
                        if ki is not None and ki.blame == "svd":
                            reg["offset"] = hdr_abs - per["base_address"]
                            reg["address_source"] = "header"
                            stats["registers_corrected"] += 1
                        elif ki is None:
                            stats["registers_conflict"] += 1
                            stats["register_conflicts"].append(
                                f"{per['name']}.{reg['name']}: "
                                f"svd 0x{svd_abs:X} vs header 0x{hdr_abs:X}")

            fields = reg.get("fields")
            if not fields:
                continue
            for fld in fields:
                svd_name, svd_bit = fld["name"], fld["bit"]
                macro, header_bit, stage = header.lookup_field_macro(
                    reg["name"], svd_name, instance, per["name"],
                    per["group_name"])
                if macro is None:
                    if stage == "ambiguous":
                        stats["fields_ambiguous"] += 1
                        continue
                    variants = dev.register_name_variants(
                        reg["name"], per["name"], per["group_name"])
                    if not header.has_pos_macros(*variants):
                        stats["fields_not_modeled"] += 1
                    elif is_structural:
                        stats["fields_structural"] += 1
                    else:
                        stats["fields_unmatched"] += 1
                    continue

                stats["fields_aligned"] += 1
                if macro != svd_name:
                    fld["name"] = macro
                    fld["svd_name"] = svd_name
                    stats["fields_renamed"] += 1
                if stage != "exact":
                    fld["name_source"] = stage

                if header_bit is None or header_bit == svd_bit:
                    continue
                ki = _adjudicate_bit(known, per["name"], reg["name"],
                                     svd_name, svd_bit, header_bit)
                if ki is not None:
                    if ki.blame == "header":
                        fld["bit_source"] = "svd"
                    else:
                        fld["bit"] = header_bit
                        fld["bit_source"] = "header"
                    stats["bits_corrected"] += 1
                    stats["corrections"].append(
                        f"{per['name']}.{reg['name']}.{svd_name}: "
                        f"{svd_bit} -> {fld['bit']}（判"
                        f"{'器件头' if ki.blame == 'header' else 'SVD'}错）")
                else:
                    fld["header_bit"] = header_bit
                    fld["bit_conflict"] = True
                    stats["bits_conflict"] += 1
                    stats["conflicts"].append(
                        f"{per['name']}.{reg['name']}.{svd_name}: "
                        f"svd {svd_bit} vs header {header_bit}")
            fields.sort(key=lambda f: f["bit"])

    return stats


# --------------------------------------------------------------------------
# 产出
# --------------------------------------------------------------------------


def extract_stm32_registers(
    svd_path: Path | str,
    *,
    mcu: str,
    mcu_series: str = "stm32h7",
    platform: str = "stm32",
    chip_slug: str | None = None,
    header_path: Path | str | None = None,
    known_issues: list[Any] | None = None,
    core_header: Path | str | None = None,
) -> dict[str, Any]:
    """生成一份 registers.json。

    分组 key = 外设实例名（SVD 的权威层级，不是猜的）。
    寄存器 `name` 是裸名；绝对地址 = 外设基址 + 寄存器偏移。

    给了 `header_path` 就走第二来源对齐（位域名取器件头宏基名、位号按
    裁定表定夺）；不给则只产 SVD 原始骨架 —— 那种数据的位域名源码里
    根本不会出现，**只配调试，不该入库**。

    给了 `core_header`（`core_cm7.h`）就并入 **CMSIS 内核块**。这一步不是
    可有可无的补全：SVD 里的 `SCB` / `NVIC` / `MPU` / `FPU` 用的是 SVD 自己
    的寄存器名（`CFSR_UFSR_BFSR_MMFSR`、`SHCRS`），源码写的是
    `SCB->CFSR` / `SCB->SHCSR`，对不上就被 S2 判成幻觉寄存器；而
    `DWT` / `CoreDebug` / `SysTick` / `ITM` / `TPI` **根本没进 SVD**。
    不并这一块，任何用异常栈帧或 `DWT->CYCCNT` 计时的固件都会恒定
    源审查失败。详见 `cmsis_core` 的模块注释。
    """
    svd_path = Path(svd_path)
    parsed = parse_svd(svd_path)
    slug = chip_slug or mcu.lower()
    alignment: dict[str, Any] | None = None
    if header_path is not None:
        header_path = Path(header_path)
        alignment = align_fields_with_header(
            parsed, dev.parse_device_header(header_path),
            known_issues=known_issues)

    groups: dict[str, dict[str, Any]] = {}
    for per in parsed["peripherals"]:
        rows: list[dict[str, Any]] = []
        for reg in per["registers"]:
            entry: dict[str, Any] = {
                "name": reg["name"],
                "address": f"0x{per['base_address'] + reg['offset']:X}",
                "size": reg["size"],
                "source": f"CMSIS-SVD {svd_path.name}",
            }
            if "access" in reg:
                entry["access"] = reg["access"]
            if "reset" in reg:
                entry["reset"] = reg["reset"]
            # 地址被裁定修正过就留痕 —— 否则「数据里的地址与 SVD 不同」
            # 这件事无从追溯，下次比对会以为生成器算错了。
            if reg.get("address_source"):
                entry["address_source"] = reg["address_source"]
            if reg.get("fields"):
                entry["fields"] = reg["fields"]
            rows.append(entry)

        if not rows:
            continue
        desc = f"SVD peripheral {per['name']} (base 0x{per['base_address']:X})"
        if per["group_name"]:
            desc += f", groupName {per['group_name']}"
        groups[per["name"]] = {"description": desc, "registers": rows}

    # 计数先在并入内核块之前存一份 —— 之后就查不到 SVD 侧的原始规模了，
    # 而「SVD 收了多少 / 内核块补了多少」是两份独立证据，报告里要分开。
    svd_counts = _count_groups(groups)

    core_info: dict[str, Any] | None = None
    if core_header is not None:
        core_header = Path(core_header)
        core_groups, core_info = core.build_core_groups(core_header,
                                                       svd_groups=groups)
        # 同名组由 CMSIS 覆盖：源码里写的是 CMSIS 结构体成员名，SVD 的写法
        # 在这几个内核外设上反而是错的一方（`SHCRS` 是 SVD 自己的拼写错误）。
        # 被覆盖的 SVD 组不静默丢弃 —— 名字差异逐条记进 core_info。
        replaced = sorted(n for n in core_groups if n in groups)
        for name, grp in core_groups.items():
            groups[name] = grp
        core_info["replaced_svd_groups"] = replaced
        core_info["counts"] = _count_groups(
            {n: groups[n] for n in core_groups})

    counts = _count_groups(groups)

    return {
        "$schema": "knowledge/schema/registers.schema.json",
        "$id": f"cache/knowledge/{platform}/{slug}/registers.json",
        "platform": platform,
        "mcu": mcu,
        "mcu_series": mcu_series,
        "version": "1.1.0",
        "source": (f"Generated from CMSIS-SVD {svd_path.name} "
                   f"(device {parsed['device']}, version {parsed['version']}) "
                   + (f"+ CMSIS Core {Path(core_header).name} "
                      if core_info else "")
                   + f"by {EXTRACTOR_VERSION}"),
        "description": ("寄存器骨架 —— 由厂商 CMSIS-SVD 生成，**不含**寄存器/位域"
                        "的语义描述与数据手册章节引用（与 AVR 骨架同口径）。"
                        "分组 key 是 SVD 的外设层级；寄存器为裸名，"
                        "限定名按 '外设.寄存器' 现拼。"
                        + ("内核外设（SCB / NVIC / SysTick / ITM / DWT / TPI / "
                           "MPU / FPU / CoreDebug / SCnSCB）取自 ARM 官方 "
                           "CMSIS Core 头，**不用 SVD 的写法** —— 源码里写的、"
                           "编译器认的都是 CMSIS 结构体成员名。"
                           if core_info else "真机验证前属 known 级。")),
        "register_groups": groups,
        "_generator": {
            "name": "firmforge.knowledge.extractors.stm32_registers",
            "version": EXTRACTOR_VERSION,
            "source_file": svd_path.name,
            "source_sha256": sha256_of(svd_path),
            "device": parsed["device"],
            "svd_version": parsed["version"],
            # 这里**不写时间戳与耗时**：派生物的判据是「同样的输入重新跑
            # 一遍，结果 bit-identical」（分区标准 §3 / §8.3）。时间戳一进来，
            # 输出 SHA256 每次都变，lock 就永远对不上，「一致即复用」失效。
            # 生成时间属元数据，落在同目录的 lock.json 里。
            "header": ({
                "file": header_path.name,
                "sha256": sha256_of(header_path),
                "parser_version": dev.PARSER_VERSION,
                "alignment": {
                    **alignment,
                    # 明细只留头部：正常应全是空列表，非空时前 50 条足够
                    # 定位问题；全量以比对报告（parity）为准。
                    "corrections": alignment["corrections"][:50],
                    "conflicts": alignment["conflicts"][:50],
                    "register_conflicts": alignment["register_conflicts"][:50],
                },
            } if header_path is not None else None),
            "core": ({
                **core_info,
                # 与 header 同理：明细留头部，全量靠重跑定位。
                "problems": core_info["problems"][:50],
                "offset_conflicts": core_info["offset_conflicts"][:50],
                "svd_name_differences": core_info["svd_name_differences"][:100],
                "unresolved_fields": core_info["unresolved_fields"][:50],
                "sha256": sha256_of(core_header),
            } if core_info else None),
            "counts": counts,
            # SVD 侧的原始规模 —— 供核对「内核块到底补了多少」
            "svd_counts": svd_counts,
        },
    }


def _count_groups(groups: dict[str, dict[str, Any]]) -> dict[str, int]:
    """从分组表**数**规模，而不是在循环里累加。

    累加器的问题是「并组 / 覆盖 / 跳过」之后容易与真实内容脱节，而这份
    数字要进 lock.json 参与比对 —— 数出来的不会错位。
    """
    return {
        "peripherals": len(groups),
        "registers": sum(len(g.get("registers", ())) for g in groups.values()),
        "fields": sum(len(r.get("fields", ()))
                      for g in groups.values()
                      for r in g.get("registers", ())),
    }


def sha256_of(path: Path | str) -> str:
    """文件 SHA256 —— 进 lock.json，用于判定「源变了没」。"""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def default_svd_name(mcu_series: str = "stm32h7") -> str:
    """本项目用到的 SVD 文件名（H743 与 H742 同 die，取 H743 那份）。"""
    return "STM32H743x.svd"


def registers_path(mcu: str, platform: str = "stm32",
                   series: str | None = None) -> Path:
    """本芯片知识库文件的目标路径（B 区，见 `paths.knowledge_cache_dir`）。

    层级 ``<平台>/<系列>/<芯片>``：系列缺省时按型号推断（``stm32h743zit6``
    → ``stm32h7``）。同平台多代芯片不能平铺在一层 —— 见
    ``paths.series_scope`` 的说明。
    """
    from firmforge.infrastructure import paths
    if series is None:
        from firmforge.knowledge.platforms import device_series
        series = device_series(None, mcu)
    return (paths.scoped_chip_dir(paths.knowledge_cache_dir(), platform, series, mcu)
            / "registers.json")


def write_registers(result: dict[str, Any], path: Path | str) -> Path:
    """写出 registers.json（UTF-8、不转义中文、末尾换行）。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    return path


def _display_path(path: Path) -> str:
    """lock 里记 `~/...` 而不是绝对路径 —— 换机器后仍可读。"""
    path = Path(path).resolve()
    try:
        return "~/" + path.relative_to(Path.home().resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def build_lock(result: dict[str, Any], *, output_path: Path | str,
               inputs: list[Path | str], params: dict[str, Any],
               elapsed_ms: float | None = None) -> dict[str, Any]:
    """lock.json —— derived 目录可被安全丢弃的唯一依据（分区标准 R6）。

    四样指纹缺一不可：输入（源文件 SHA256）、生成器版本、参数指纹、
    输出 SHA256。任一不符即视为失效：源变了要重生成，生成器改了要重生成，
    参数（芯片 / 是否对齐）变了也要重生成。
    """
    out = Path(output_path)
    inp = {_display_path(Path(p)): sha256_of(p) for p in inputs}
    params_hash = hashlib.sha256(
        json.dumps(params, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    lock: dict[str, Any] = {
        "schema": "knowledge/lock/v1",
        "kind": "derived",
        "generator": "firmforge.knowledge.extractors.stm32_registers",
        "generator_version": EXTRACTOR_VERSION,
        "params": params,
        "params_hash": params_hash,
        "inputs": inp,
        "output": out.name,
        "output_sha256": sha256_of(out),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "counts": result.get("_generator", {}).get("counts", {}),
    }
    if elapsed_ms is not None:
        lock["elapsed_ms"] = round(elapsed_ms, 1)
    return lock


def main(argv: list[str] | None = None) -> int:
    """命令行入口。

    Usage::

        python -m firmforge.knowledge.extractors.stm32_registers \\
            [--mcu stm32h743zit6] [--svd PATH] [--header PATH]
            [--core-header PATH] [--out PATH]
    """
    import argparse

    ap = argparse.ArgumentParser(
        description="从厂商 CMSIS-SVD 生成 STM32 寄存器知识库（B 区）")
    ap.add_argument("--mcu", default="stm32h743zit6")
    ap.add_argument("--series", help="芯片系列（缺省按型号推：stm32h743zit6 -> stm32h7）")
    ap.add_argument("--svd", type=Path, help="SVD 路径（缺省查 B 区缓存）")
    ap.add_argument("--header", type=Path, help="器件头路径（缺省查 packages）")
    ap.add_argument("--core-header", type=Path,
                    help="CMSIS Core 头路径（缺省查 packages/stm32/cmsis_5）")
    ap.add_argument("--out", type=Path, help="输出路径（缺省 B 区 cache）")
    ap.add_argument("--no-align", action="store_true",
                    help="跳过器件头对齐（仅调试；产物位域名是 SVD 名）")
    ap.add_argument("--no-core", action="store_true",
                    help="不并入内核寄存器块（仅调试；SCB/DWT/CoreDebug 将缺失）")
    ap.add_argument("--json", action="store_true", dest="as_json")
    args = ap.parse_args(argv)

    from firmforge.knowledge.parity import (
        STM32_DEVICES, default_cmsis_include, find_svd)
    from firmforge.knowledge.platforms import device_series

    if args.mcu not in STM32_DEVICES:
        print(f"未登记的器件: {args.mcu}（见 parity.STM32_DEVICES）",
              file=sys.stderr)
        return 2
    svd_name, header_name = STM32_DEVICES[args.mcu]
    series = args.series or device_series(None, args.mcu)

    svd = Path(args.svd) if args.svd else find_svd(svd_name, series)
    if not svd.is_file():
        print(f"找不到 SVD: {svd_name}（先下载到 B 区 "
              f"cache/knowledge/_sources/{series}/）", file=sys.stderr)
        return 2

    header: Path | None = None
    if not args.no_align:
        header = (Path(args.header) if args.header
                  else default_cmsis_include() / header_name)
        if not header.is_file():
            print(f"找不到器件头: {header}", file=sys.stderr)
            return 2

    core_header: Path | None = None
    if not args.no_core:
        core_header = args.core_header or core.default_core_header()
        if core_header is None or not core_header.is_file():
            # 缺内核块不是「少一点数据」：SCB / DWT 缺失会让任何做异常
            # 栈帧或周期计时的固件在源审查里恒定失败。所以默认行为是
            # 报错退出，要生成残缺数据必须显式 --no-core。
            from firmforge.infrastructure import paths
            print("找不到 CMSIS Core 头（core_cm7.h），已查 "
                  f"{paths.packages_dir() / 'stm32' / 'cmsis_5'}/<ver>/"
                  "CMSIS/Core/Include/\n"
                  "    下载 ARM-software/CMSIS_5 的 CMSIS/Core/Include 到该"
                  "目录即可，或用 --core-header 指定；\n"
                  "    确认要生成缺内核块的数据请显式 --no-core。",
                  file=sys.stderr)
            return 2

    t0 = time.time()
    result = extract_stm32_registers(svd, mcu=args.mcu, header_path=header,
                                     core_header=core_header)
    out = Path(args.out) if args.out else registers_path(args.mcu, series=series)
    write_registers(result, out)

    params = {
        "mcu": args.mcu, "mcu_series": series,
        "align": header is not None,
        # 内核块的有无 / 版本会改变份数据内容，必须进参数指纹，
        # 否则换一份 CMSIS 头重跑会被判成「一致即复用」。
        "core": core_header.name if core_header else None,
    }
    inputs: list[Path] = [svd] + ([header] if header else [])
    if core_header:
        inputs.append(core_header)
    lock = build_lock(result, output_path=out, inputs=inputs, params=params,
                      elapsed_ms=(time.time() - t0) * 1000)
    lock_path = out.parent / "lock.json"
    lock_path.write_text(json.dumps(lock, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")

    counts = result["_generator"]["counts"]
    svd_counts = result["_generator"]["svd_counts"]
    core_info = result["_generator"].get("core") or {}
    align = (result["_generator"].get("header") or {}).get("alignment") or {}
    if args.as_json:
        print(json.dumps({"output": str(out), "lock": str(lock_path),
                          "counts": counts, "svd_counts": svd_counts,
                          "core": core_info, "alignment": align},
                         ensure_ascii=False, indent=2))
        return 0

    print(f"寄存器 {counts['registers']} / 位域 {counts['fields']} "
          f"/ 外设 {counts['peripherals']}")
    if core_info:
        cc = core_info["counts"]
        print(f"  其中内核块: 寄存器 {cc['registers']} / 位域 {cc['fields']} "
              f"/ 外设 {cc['peripherals']}"
              f"（并入 {core_info['source_file']}，"
              f"覆盖 SVD 同名组 {', '.join(core_info['replaced_svd_groups']) or '无'}）")
        print(f"  SVD 侧原始: 寄存器 {svd_counts['registers']} / "
              f"位域 {svd_counts['fields']} / 外设 {svd_counts['peripherals']}")
        if core_info["offset_conflicts"]:
            print(f"  ! 内核寄存器偏移交叉验证不一致 {len(core_info['offset_conflicts'])} 条")
        if core_info["unresolved_fields"]:
            print(f"  ! 位号求值不出 {len(core_info['unresolved_fields'])} 条")
        for problem in core_info["problems"]:
            print(f"  ! {problem}")
    if align:
        print(f"器件头对齐: 命中 {align['fields_aligned']}，"
              f"改名 {align['fields_renamed']}")
        print(f"  名字未对上的原因: 真命名问题 {align['fields_unmatched']}，"
              f"结构差异 {align['fields_structural']}，"
              f"器件头未建模 {align['fields_not_modeled']}，"
              f"无实例 {align['fields_no_instance']}，"
              f"歧义 {align['fields_ambiguous']}")
        print(f"位号: 修正 {align['bits_corrected']}，"
              f"未裁定冲突 {align['bits_conflict']}")
        print(f"寄存器地址: 修正 {align['registers_corrected']}，"
              f"未裁定冲突 {align['registers_conflict']}")
        for conflict in align["register_conflicts"]:
            print(f"  ! {conflict}")
        for conflict in align["conflicts"]:
            print(f"  ! {conflict}")
        if align["peripherals_unmapped"]:
            print("器件头无实例: " + ", ".join(align["peripherals_unmapped"]))
    print(f"输出: {out}")
    print(f"lock: {lock_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
