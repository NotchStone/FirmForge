"""生成器 ↔ 人工金标准 的一致性比对。

用途
----
`avr_registers` 生成器产出的是**骨架**，`data/knowledge/reference/avr/<mcu>/`
下的人工制品是**承诺级金标准**（A 区入库）。两者比对回答一个问题：

    「生成器现在能不能覆盖人工那份数据？」

比对刻意分三类，**严重程度不同**，不要混成一个布尔值：

======================  ====================================================
类别                     含义
======================  ====================================================
``registers_missing``    金标准有、生成器没有 → 生成器漏了硬件，**必须修**
``bits_missing``         同上，细化到「寄存器 + 位号」
``registers_extra``      生成器有、金标准没有 → 生成器发现了人工尚未收录
                         的真实寄存器，**不改生成器**，供人工决定是否收编
``bits_extra``           同上
``address_mismatch``     同名寄存器地址不同 → 必有一方错，**需人工裁定**
``bit_mismatch``         同名位域位号不同 → 必有一方错，**需人工裁定**
``bit_names_unknown``    金标准的位名在器件头里查无此名 → 拼写错，或只是
                         命名口径不同（见下 `_field_known`）
======================  ====================================================

「多出来」为什么不算错：金标准是人工**筛选**过的承诺子集（例如端口数据
寄存器只记地址、不逐个列 DDA0..DDA7 位），生成器覆盖全硬件必然更大。
只有「缺失」「同名不同值」「位名查无此名」才是真问题。

位名为什么要单独查
------------------
位号对、位名错是最阴的一类：汇编器/编译器只认宏名，``TXB08`` 与 ``TXB80``
位号都是 0，靠位号比对永远不会报，而写 ``UCSR0B |= (1 << TXB08)`` 的代码
根本编不过。2026-09-16 就是靠这一项从金标准里挖出 8 条转置错
（2560 的 4 个 USART 全是 ``TXBx8``，而 328p 那份写的是对的 ``TXB8x``）。

命名口径 vs 拼写错
------------------
avr-libc 对部分位加寄存器名前缀（``SREG_C`` 而数据手册写 ``C``），位号一致，
**不是错误**。所以判定顺序是：先精确匹配，再试 ``<寄存器>_<位名>``，
都不中才算查无此名。

地址口径
--------
一律用**内存映射地址**：I/O 空间寄存器按 `+0x20` 折算，与数据手册的
Register Summary 一致。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from firmforge.knowledge.extractors import avr_registers as ex


@dataclass
class McuParity:
    """单个 MCU 的比对结果。"""

    mcu: str
    header: str
    register_source: str = ""
    conditional_filter_applied: bool = False
    golden_registers: int = 0
    generated_registers: int = 0
    golden_bits: int = 0
    generated_bits: int = 0
    registers_missing: list[str] = field(default_factory=list)
    registers_extra: list[str] = field(default_factory=list)
    bits_missing: list[tuple[str, int]] = field(default_factory=list)
    bits_extra: list[tuple[str, int]] = field(default_factory=list)
    address_mismatch: dict[str, tuple[str, str]] = field(default_factory=dict)
    bit_mismatch: dict[tuple[str, str], tuple[int, int]] = field(
        default_factory=dict)
    bit_names_unknown: list[tuple[str, str]] = field(default_factory=list)

    @property
    def covered(self) -> bool:
        """覆盖性是否达标 —— 只看「缺失」。"""
        return not self.registers_missing and not self.bits_missing

    @property
    def consistent(self) -> bool:
        """同名值是否一致 —— 不一致就是有人错了。"""
        return not self.address_mismatch and not self.bit_mismatch

    @property
    def sound(self) -> bool:
        """覆盖 + 一致 + 位名可解析。"""
        return self.covered and self.consistent and not self.bit_names_unknown

    def to_dict(self) -> dict:
        return {
            "mcu": self.mcu,
            "header": self.header,
            "register_source": self.register_source,
            "conditional_filter_applied": self.conditional_filter_applied,
            "counts": {
                "golden_registers": self.golden_registers,
                "generated_registers": self.generated_registers,
                "golden_bits": self.golden_bits,
                "generated_bits": self.generated_bits,
            },
            "covered": self.covered,
            "consistent": self.consistent,
            "sound": self.sound,
            "registers_missing": self.registers_missing,
            "registers_extra": self.registers_extra,
            "bits_missing": [list(x) for x in self.bits_missing],
            "bits_extra": [list(x) for x in self.bits_extra],
            "address_mismatch": {k: list(v)
                                 for k, v in self.address_mismatch.items()},
            "bit_mismatch": {f"{k[0]}.{k[1]}": list(v)
                             for k, v in self.bit_mismatch.items()},
            "bit_names_unknown": [list(x) for x in self.bit_names_unknown],
        }


def load_golden(path: Path) -> tuple[dict[str, int], dict[str, dict[str, int]]]:
    """读人工金标准，返回 ``({寄存器: 地址}, {寄存器: {位域名: 位号}})``。"""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    addresses: dict[str, int] = {}
    fields: dict[str, dict[str, int]] = {}
    for group in data.get("register_groups", {}).values():
        for reg in group.get("registers", []) or []:
            name = reg["name"]
            addresses[name] = int(str(reg["address"]), 16)
            fields.setdefault(name, {})
            for f in reg.get("fields", []) or []:
                fields[name][f["name"]] = int(f["bit"])
    return addresses, fields


def _field_known(reg: str, name: str, gen_fields: dict[str, int]) -> bool:
    """金标准的位名能否在器件头里找到对应。

    两段判定：

    1. 精确同名 —— 绝大多数情况。
    2. ``<寄存器>_<位名>`` —— avr-libc 对部分位加寄存器名前缀
       （``SREG_C`` / ``SREG_Z`` … 而数据手册写 ``C`` / ``Z``）。
       位号一致，属**命名口径**，不是错误。
    """
    return name in gen_fields or f"{reg}_{name}" in gen_fields


def compare_one(mcu: str, header: Path, golden: Path,
                *, avr_gcc: str | None = None) -> McuParity:
    """比对单个 MCU。"""
    g_addr, g_fields = load_golden(golden)
    parsed = ex.parse_device_header(header, avr_gcc=avr_gcc)

    gen_addr = {r["name"]: int(r["address"], 16) for r in parsed["registers"]}
    gen_fields = {r["name"]: {f["name"]: f["bit"] for f in r["_fields"]}
                  for r in parsed["registers"]}

    rep = McuParity(mcu=mcu, header=header.name)
    info = parsed["conditional_filter"]
    rep.register_source = info.get("register_source", "")
    rep.conditional_filter_applied = bool(info.get("applied"))

    rep.golden_registers = len(g_addr)
    rep.generated_registers = len(gen_addr)
    rep.golden_bits = sum(len(v) for v in g_fields.values())
    rep.generated_bits = sum(len(v) for v in gen_fields.values())

    rep.registers_missing = sorted(set(g_addr) - set(gen_addr))
    rep.registers_extra = sorted(set(gen_addr) - set(g_addr))
    rep.address_mismatch = {
        n: (f"0x{g_addr[n]:X}", f"0x{gen_addr[n]:X}")
        for n in sorted(set(g_addr) & set(gen_addr))
        if g_addr[n] != gen_addr[n]
    }

    g_bits = {(n, b) for n, fs in g_fields.items() for b in fs.values()}
    gen_bits = {(n, b) for n, fs in gen_fields.items() for b in fs.values()}
    rep.bits_missing = sorted(g_bits - gen_bits)
    rep.bits_extra = sorted(gen_bits - g_bits)

    rep.bit_mismatch = {}
    for reg in sorted(set(g_fields) & set(gen_fields)):
        for name in sorted(set(g_fields[reg]) & set(gen_fields[reg])):
            if g_fields[reg][name] != gen_fields[reg][name]:
                rep.bit_mismatch[(reg, name)] = (
                    g_fields[reg][name], gen_fields[reg][name])

    # 位名可解析性 —— 位号对但名字拼错时，唯一的拦截点。
    rep.bit_names_unknown = sorted(
        (reg, name)
        for reg, names in g_fields.items()
        if reg in gen_fields
        for name in names
        if not _field_known(reg, name, gen_fields[reg])
    )
    return rep


#: 本机金标准覆盖的 MCU —— MCU 名 → 器件头文件名。
GOLDEN_DEVICES: dict[str, str] = {
    "atmega2560": "iom2560.h",
    "atmega328p": "iom328p.h",
}


def compare_all(repo_root: Path, include_dir: Path | None = None,
                *, avr_gcc: str | None = None) -> list[McuParity]:
    """比对本机全部金标准 MCU。"""
    repo_root = Path(repo_root)
    include_dir = include_dir or ex.default_avr_include_dir()
    out: list[McuParity] = []
    for mcu, header_name in GOLDEN_DEVICES.items():
        out.append(compare_one(
            mcu,
            Path(include_dir) / header_name,
            ex.golden_registers_path(mcu, repo_root),
            avr_gcc=avr_gcc,
        ))
    return out


def render_text(reports: list[McuParity]) -> str:
    """人类可读报告。"""
    lines: list[str] = []
    for rep in reports:
        lines.append("=" * 72)
        lines.append(f"{rep.mcu}  (header: {rep.header})")
        lines.append(f"  寄存器来源: {rep.register_source}")
        lines.append(f"  条件过滤:   {'生效' if rep.conditional_filter_applied else '未生效'}")
        lines.append(f"  寄存器:     金标准 {rep.golden_registers} / 生成器 {rep.generated_registers}")
        lines.append(f"  位域:       金标准 {rep.golden_bits} / 生成器 {rep.generated_bits}")
        lines.append(f"  覆盖性:     {'OK' if rep.covered else '缺失 → 生成器需修'}")
        lines.append(f"  一致性:     {'OK' if rep.consistent else '有同名不同值 → 需人工裁定'}")
        lines.append(f"  位名可解析: {'OK' if not rep.bit_names_unknown else '查无此名 → 拼写错或口径未登记'}")

        def _dump(title: str, items: list) -> None:
            if not items:
                return
            lines.append(f"  {title} ({len(items)}):")
            for it in items[:20]:
                lines.append(f"    - {it}")
            if len(items) > 20:
                lines.append(f"    … 其余 {len(items) - 20} 条")

        _dump("金标准有、生成器缺（寄存器）", rep.registers_missing)
        _dump("金标准有、生成器缺（位）", rep.bits_missing)
        _dump("地址不一致（金标准 vs 器件头）",
              [f"{n}: {g} vs {h}" for n, (g, h) in rep.address_mismatch.items()])
        _dump("位号不一致（金标准 vs 器件头）",
              [f"{r}.{n}: {g} vs {h}"
               for (r, n), (g, h) in rep.bit_mismatch.items()])
        _dump("位名查无此名（金标准 vs 器件头）",
              [f"{r}.{n}" for r, n in rep.bit_names_unknown])
        lines.append(f"  （生成器多出：寄存器 {len(rep.registers_extra)}、"
                     f"位 {len(rep.bits_extra)} —— 金标准是人工筛选子集，不算错）")
    lines.append("=" * 72)
    return "\n".join(lines)
