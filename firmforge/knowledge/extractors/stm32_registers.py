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
"""

from __future__ import annotations

import hashlib
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

#: 生成器版本 —— 参与 lock.json 的失效判定。
#: **改提取逻辑必须递增它**，否则「改了规则但缓存没失效」会变成幽灵 bug。
EXTRACTOR_VERSION = "stm32-registers/1.0.0"

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
# 产出
# --------------------------------------------------------------------------


def extract_stm32_registers(
    svd_path: Path | str,
    *,
    mcu: str,
    mcu_series: str = "stm32h7",
    platform: str = "stm32",
    chip_slug: str | None = None,
) -> dict[str, Any]:
    """生成一份 registers.json 骨架。

    分组 key = 外设实例名（SVD 的权威层级，不是猜的）。
    寄存器 `name` 是裸名；绝对地址 = 外设基址 + 寄存器偏移。
    """
    svd_path = Path(svd_path)
    t0 = time.time()
    parsed = parse_svd(svd_path)
    slug = chip_slug or mcu.lower()

    groups: dict[str, dict[str, Any]] = {}
    n_regs = n_fields = 0
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
            if reg.get("fields"):
                entry["fields"] = reg["fields"]
                n_fields += len(reg["fields"])
            rows.append(entry)
            n_regs += 1

        if not rows:
            continue
        desc = f"SVD peripheral {per['name']} (base 0x{per['base_address']:X})"
        if per["group_name"]:
            desc += f", groupName {per['group_name']}"
        groups[per["name"]] = {"description": desc, "registers": rows}

    return {
        "$schema": "knowledge/schema/registers.schema.json",
        "$id": f"cache/knowledge/{platform}/{slug}/registers.json",
        "platform": platform,
        "mcu": mcu,
        "mcu_series": mcu_series,
        "version": "1.0.0",
        "source": (f"Generated from CMSIS-SVD {svd_path.name} "
                   f"(device {parsed['device']}, version {parsed['version']}) "
                   f"by {EXTRACTOR_VERSION}"),
        "description": ("寄存器骨架 —— 由厂商 CMSIS-SVD 生成，**不含**寄存器/位域"
                        "的语义描述与数据手册章节引用（与 AVR 骨架同口径）。"
                        "分组 key 是 SVD 的外设层级；寄存器为裸名，"
                        "限定名按 '外设.寄存器' 现拼。真机验证前属 known 级。"),
        "register_groups": groups,
        "_generator": {
            "name": "firmforge.knowledge.extractors.stm32_registers",
            "version": EXTRACTOR_VERSION,
            "source_file": svd_path.name,
            "source_sha256": sha256_of(svd_path),
            "device": parsed["device"],
            "svd_version": parsed["version"],
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "elapsed_ms": round((time.time() - t0) * 1000, 1),
            "counts": {
                "peripherals": len(groups),
                "registers": n_regs,
                "fields": n_fields,
            },
        },
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


def golden_registers_path(mcu: str, repo_root: Path) -> Path:
    """本芯片知识库文件的目标路径（B 区，见 paths.knowledge_cache_dir）。"""
    from firmforge.infrastructure import paths
    return paths.knowledge_cache_dir() / "stm32" / mcu.lower() / "registers.json"
