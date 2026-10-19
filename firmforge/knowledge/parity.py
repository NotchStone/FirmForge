"""生成器 ↔ 第二来源 的一致性比对（AVR 与 STM32 两条线）。

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



# ==========================================================================
# STM32：SVD 生成器 ↔ CMSIS 器件头
# ==========================================================================
#
# AVR 那条线比的是「生成器 ↔ 人工金标准」，STM32 这条线比的是
# 「SVD ↔ 器件头」——两个都是机器可读的厂商制品。差异带来的口径变化：
#
# * AVR 的「多出来不算错」在这里**不适用**：器件头是全量建模，没有人工筛选
#   子集一说，所以寄存器/位域的缺失是真信息（器件头未建模，或 SVD 多了东西）。
# * 新增「基址」这一类 —— SVD 与器件头各自独立给出基址，不一致就是硬错。
# * 位号比对多两个「非错误」态：器件头压根没建模这个寄存器的位
#   （`bits_not_modeled`），或宏名口径对不上（`bits_unresolved`）。
#   两者都必须逐条列出来，不能静默丢（对齐 AVR 侧 conditional_filter 的留痕原则）。
#
# 三类严重度：
#   ``base_mismatch`` / ``offset_mismatch`` / ``bits_mismatch``
#       → 值不同，**必有一方错**，除非命中已知缺陷表
#   ``registers_not_modeled`` / ``bits_unresolved`` / ``bits_not_modeled``
#       → SVD 有、器件头找不到对等物：器件头未建模，或 SVD 多出字段
#   ``unmapped`` / ``no_instance`` / ``skipped_core`` / ``structural_exempt``
#       → 没比到，逐条给理由
#
# 地址一律比**绝对地址**（基址 + 偏移），不比偏移本身。原因是 SVD 会把器件
# 头里的一个外设拆成几个（`Ethernet_MAC/MTL/DMA` 对 `ETH`），各段基址不同，
# 比偏移会得到满屏假冲突；换成绝对地址后它们自动对上（实测 76 条假冲突归零，
# 只剩真缺陷）。


def _glob(pattern: str, value: str) -> bool:
    """极简通配 —— 只支持一个 `*`（`DINR*` / `AWD*CH` / `AWD*CR`）。

    不引 `fnmatch`：这里只需要「前缀 + 后缀」一种形式，多引一套匹配语义
    反而让「这条规则到底盖住了什么」更难看清。
    """
    if not pattern:
        return True
    if "*" not in pattern:
        return pattern == value
    prefix, suffix = pattern.split("*", 1)
    return value.startswith(prefix) and value.endswith(suffix)


@dataclass
class KnownIssue:
    """已裁定的缺陷 —— 命中即不报冲突，但比对结果一变就报「表已失效」。

    判定一律用**增量**而不是绝对值（`header - svd`）：绝对地址随芯片变，
    而「差 4 字节」这件事是缺陷的本体。用绝对值写会把表写死成 H743 专用，
    换芯片时全表失效却看不出原因。

    ``register`` 支持**前缀通配**（尾部 `*`）：`MDIOS.DINR*` 一次覆盖
    DINR0..DINR19 —— 它们本就是同一个漏掉保留区的缺陷，写 20 行会把
    「一个事实」拆成 20 条记录。

    ``blame`` 记录**判谁错**：多数是 SVD 错（器件头与单片机手册一致），
    但也有器件头自己错的情况（`EXTI_D3PMR1.MR25` 位号写成 24）。
    不记这一项就会默认「SVD 错」，把结论带偏。
    """

    peripheral: str
    register: str
    kind: str                       # "base" | "offset" | "bit" | "bit_shift"
    delta: int = 0                  # base/offset/bit_shift：器件头 - SVD
    svd_value: int = 0              # bit：绝对值（小整数，稳定）
    header_value: int = 0           # bit：绝对值
    field: str = ""
    blame: str = "svd"              # "svd" | "header"
    reason: str = ""

    def covers(self, peripheral: str, register: str, kind: str,
               field: str = "") -> bool:
        if self.peripheral != peripheral or self.kind != kind:
            return False
        if not _glob(self.register, register) or not _glob(self.field, field):
            return False
        return True

    def matches(self, svd_value: int, header_value: int) -> bool:
        if self.kind in ("base", "offset", "bit_shift"):
            return header_value - svd_value == self.delta
        return (svd_value, header_value) == (self.svd_value, self.header_value)

    @property
    def key(self) -> tuple[str, str, str, str]:
        return (self.peripheral, self.register, self.kind, self.field)

    def describe(self) -> str:
        what = f"{self.peripheral}.{self.register}"
        if self.field:
            what += f".{self.field}"
        side = "SVD 错" if self.blame == "svd" else "**器件头错**"
        if self.kind == "bit_shift":
            return (f"{what} [位号整体偏移 +{self.delta}]（{side}）—— {self.reason}")
        if self.kind == "bit":
            return (f"{what} [bit] SVD={self.svd_value} 器件头={self.header_value}"
                    f"（{side}）—— {self.reason}")
        return (f"{what} [{self.kind}] 器件头比 SVD {self.delta:+d} 字节"
                f"（{side}）—— {self.reason}")


#: 已裁定的缺陷。
#: **每条都必须写清"凭什么这么判"**（取证对象：器件头与单片机手册两边对齐），
#: 否则下一个人只能重新查一遍。
STM32_KNOWN_ISSUES: list[KnownIssue] = [
    KnownIssue(
        peripheral="CRC", register="INIT", kind="offset", delta=+4,
        reason="SVD 漏掉 0x0C 的保留字，INIT/POL 整体前移 4 字节",
    ),
    KnownIssue(
        peripheral="CRC", register="POL", kind="offset", delta=+4,
        reason="同上（INIT 前移的连带项）",
    ),
    KnownIssue(
        peripheral="MDIOS", register="DINR*", kind="offset", delta=+0xE4,
        reason="SVD 漏掉 DINR0 前 57 个字的保留区（0xE4）；器件头 RESERVED[57]"
               "+ 前 7 个配置寄存器 = 0x100，SVD 只说 0x1C",
    ),
    KnownIssue(
        peripheral="MDIOS", register="DOUTR*", kind="offset", delta=+0xE4,
        reason="同 DINR*（同一个漏掉保留区的缺陷，输出寄存器这一半）",
    ),
    KnownIssue(
        peripheral="HRTIM_Common", register="BDMADR", kind="offset", delta=+0x10,
        reason="SVD 把 5 个更新寄存器塌缩成一个 `BDTxUPR`，于是把 BDMADR "
               "提前了 4 个字（0x60→0x70）；器件头 BDTAUPR..BDTEUPR 五个都在",
    ),
    KnownIssue(
        peripheral="Flash", register="PRAR_PRG2", kind="offset", delta=+0x100,
        reason="SVD 把这个 bank2 寄存器错写成 bank1 的偏移；同外设 CR2/SR2/"
               "PRAR_CUR2 都在 +0x100 上，只此一条漏加",
    ),
    KnownIssue(
        peripheral="Ethernet_MAC", register="MACARPAR", kind="offset",
        delta=-0x8D0,
        reason="SVD 写成 0xAE0，但它在 SVD 自己的寄存器表里夹在 0x204 与 "
               "0x300 之间、顺序就已经不对；0x210 才是手册与器件头一致的地址",
    ),
    KnownIssue(
        peripheral="Flash", register="CRCCR*", kind="bit", field="ALL_BANK",
        svd_value=7, header_value=22,
        reason="手册 FLASH_CRCCR 的 ALL_BANK 在 bit 22（紧接 START_CRC=16 之后）；"
               "SVD 写 7 —— 而 bit 7 在 SVD 自己的表里已被 CRC_SECT(0-2) 与"
               "后续位占满，属 SVD 自相矛盾",
    ),
    KnownIssue(
        peripheral="SYSCFG", register="UR3", kind="bit", field="BOOT_ADD1",
        svd_value=16, header_value=0, blame="header",
        reason="器件头把 BOOT_ADD1 放在 bit 0，且同寄存器里**没有 BOOT_ADD0 "
               "宏**；手册是 BOOT_ADD0 占 15:0、BOOT_ADD1 占 31:16。SVD 对",
    ),
    KnownIssue(
        peripheral="ADC1", register="AWD*CR", kind="bit", field="AWD*CH",
        svd_value=1, header_value=0,
        reason="SVD 把 AWDxCH 的起始位写成 1（并为它编了 width=20），"
               "器件头与手册都是 bit 0、宽 5 位",
    ),
    KnownIssue(
        peripheral="ADC2", register="AWD*CR", kind="bit", field="AWD*CH",
        svd_value=1, header_value=0, reason="同 ADC1",
    ),
    KnownIssue(
        peripheral="ADC3", register="AWD*CR", kind="bit", field="AWD*CH",
        svd_value=1, header_value=0, reason="同 ADC1",
    ),
    KnownIssue(
        peripheral="BDMA", register="ISR", kind="bit_shift", delta=+4,
        reason="SVD 少了整个通道 0 的位域组，通道 1 起的所有位号被顶低 4 位"
               "（器件头有 GIF0=0/TCIF0=1/TEIF0=3）；照 SVD 写代码必错",
    ),
    KnownIssue(
        peripheral="BDMA", register="IFCR", kind="bit_shift", delta=+4,
        reason="同 BDMA.ISR",
    ),
    KnownIssue(
        peripheral="EXTI", register="D3PMR1", kind="bit", field="MR25",
        svd_value=25, header_value=24, blame="header",
        reason="器件头把 MR25 的位号写成 24（它自己的 MR0..MR21 都是 n→n，"
               "且缺 MR16-18/MR22-24 的宏）；SVD 与手册一致，是 bit 25",
    ),
]

#: SVD 把器件头里的**一个外设拆成几段**时，各段在器件头实例内的起始偏移。
#: 不做这个补偿就会得到满屏假冲突：`Ethernet_DMA` 的基址比 `ETH` 高 0x1000，
#: 其寄存器偏移自然小 0x1000。补偿后绝对地址直接对上（自校验）。
#: **值不是猜的** —— 它是「加上去之后这一段的寄存器地址全部吻合」的那一个。
STRUCTURAL_BASE_OFFSET: dict[str, int] = {
    "COMP1": -0x0C,             # 器件头 COMP1_BASE 含结构体起点 +0xC
    "Ethernet_MTL": +0xC00,
    "Ethernet_DMA": +0x1000,
    "OTG1_HS_HOST": +0x400,
    "OTG1_HS_DEVICE": +0x800,
    "OTG1_HS_PWRCLK": +0xE00,
    "OTG2_HS_HOST": +0x400,
    "OTG2_HS_DEVICE": +0x800,
    "OTG2_HS_PWRCLK": +0xE00,
}

#: 已裁定的**结构性差异** —— 不是谁错，是两边建模粒度不同，寄存器级别
#: 无法一一对应。命中后该外设的**寄存器/位域比对整体跳过**，全部计入
#: ``structural_exempt``（带理由），不计入 ``registers_not_modeled``。
#: **每条都要写清差异是什么。**
#:
#: 注意 `Ethernet_MAC` **不在**此表里：它的粒度确实与 SVD 不同，但寄存器级
#: 比对仍然有效 —— 正是靠它发现了 SVD 把 `MACARPAR` 写成 0xAE0（见缺陷表）。
#: 粒度不同不等于比不了；能比的一定要比。
STRUCTURAL_DIFFERENCES: dict[str, str] = {
    "MDMA": "器件头未建模 MDMA_TypeDef（MDMA 寄存器以直接地址宏给出），"
            "无法做寄存器级比对",
    "DMA1": "SVD 把通道寄存器拉平（CCR1..CCR8 / CNDTR1..），器件头拆成 "
            "DMA_Stream_TypeDef 的多个实例（DMA1_Stream0..7）",
    "DMA2": "同上",
    "BDMA": "同上（器件头为 BDMA_Channel_TypeDef 实例）",
    "DMAMUX1": "器件头把 DMAMUX 的通道寄存器建成数组型结构，SVD 拉平为 "
               "C0CR/C1CR…，两边粒度不同",
    "DMAMUX2": "同上",
    "HSEM": "器件头未把 HSEM 的按核寄存器建模进结构体成员",
    "OTG1_HS_HOST": "器件头把 OTG host 段建模为数组型通道结构，"
                    "SVD 拉平为 HCCHARn/HCSPLTn…",
    "OTG2_HS_HOST": "同上",
    "OTG1_HS_DEVICE": "同上（端点寄存器组）",
    "OTG2_HS_DEVICE": "同上",
    "OTG1_HS_GLOBAL": "器件头 OTG global 段的寄存器名与 SVD 逐条同名，"
                      "但结构体只建模了部分；按 no_struct 处理",
    "OTG2_HS_GLOBAL": "同上",
    "LTDC": "器件头把 LTDC 的层寄存器建模为嵌套结构，SVD 拉平",
    "FMC": "SVD 的 FMC 覆盖 Bank1/Bank2/NOR/NAND/SDRAM 多个器件头实例，"
           "无法一对一",
    "HRTIM_TIMA": "器件头把 HRTIM 定时器建成 HRTIM_Timerx_TypeDef 共用体，"
                  "寄存器名前缀与 SVD 不同",
    "HRTIM_TIMB": "同上",
    "HRTIM_TIMC": "同上",
    "HRTIM_TIMD": "同上",
    "HRTIM_TIME": "同上",
    "HRTIM_Master": "同上",
    "HRTIM_Common": "SVD 把 HRTIM 公共寄存器的 5 个更新寄存器塌缩成一个 "
                    "`BDTxUPR`（器件头是 BDTAUPR..BDTEUPR 五个），"
                    "寄存器名无法一一对应",
}


@dataclass
class Stm32Parity:
    """单个 MCU 的 SVD ↔ 器件头 比对结果。"""

    mcu: str
    svd: str
    header: str
    parser_version: str = ""

    svd_peripherals: int = 0
    mapped_peripherals: int = 0
    svd_registers: int = 0
    registers_matched: int = 0
    svd_fields: int = 0
    fields_matched: int = 0
    header_instances: int = 0
    header_macros: int = 0

    match_kinds: dict[str, int] = field(default_factory=dict)
    field_match_kinds: dict[str, int] = field(default_factory=dict)
    base_mismatch: dict[str, tuple[int, int]] = field(default_factory=dict)
    offset_mismatch: dict[str, tuple[int, int]] = field(default_factory=dict)
    bits_mismatch: dict[str, tuple[int, int]] = field(default_factory=dict)
    registers_not_modeled: list[tuple[str, str]] = field(default_factory=list)
    structural_exempt: dict[str, list[str]] = field(default_factory=dict)
    #: 结构性差异外设里「位域名对不上」的计数 —— 预期内，不计入覆盖缺口
    structural_unresolved: dict[str, int] = field(default_factory=dict)
    bits_not_modeled: list[str] = field(default_factory=list)
    bits_unresolved: list[str] = field(default_factory=list)
    bits_ambiguous: list[str] = field(default_factory=list)
    peripherals_without_struct: list[str] = field(default_factory=list)
    unmapped: list[str] = field(default_factory=list)
    no_instance: list[str] = field(default_factory=list)
    skipped_core: list[str] = field(default_factory=list)
    structs_with_conditionals: list[str] = field(default_factory=list)
    known_hits: list[str] = field(default_factory=list)
    known_stale: list[str] = field(default_factory=list)

    @property
    def consistent(self) -> bool:
        """同名处值是否一致 —— 这三项非空就是有人错了。"""
        return not (self.base_mismatch or self.offset_mismatch
                    or self.bits_mismatch)

    @property
    def covered(self) -> bool:
        """SVD 的位域是否都已定位（排除已裁定的结构性差异）。

        **不含** ``registers_not_modeled`` / ``bits_not_modeled``：那两类是
        「器件头没建模」，不是谁错。寄存器级的真错由 ``offset_mismatch``
        （同名不同地址）负责兜住，不需要靠"名字找不到"来报错。
        """
        return not (self.bits_unresolved or self.bits_ambiguous)

    @property
    def sound(self) -> bool:
        """一致性 + 覆盖性 + 已知缺陷表未失效 + 无解析器盲区。"""
        return (self.consistent and self.covered
                and not self.known_stale
                and not self.structs_with_conditionals)

    def to_dict(self) -> dict:
        return {
            "mcu": self.mcu,
            "svd": self.svd,
            "header": self.header,
            "parser_version": self.parser_version,
            "counts": {
                "svd_peripherals": self.svd_peripherals,
                "mapped_peripherals": self.mapped_peripherals,
                "svd_registers": self.svd_registers,
                "registers_matched": self.registers_matched,
                "svd_fields": self.svd_fields,
                "fields_matched": self.fields_matched,
                "header_instances": self.header_instances,
                "header_macros": self.header_macros,
            },
            "match_kinds": dict(sorted(self.match_kinds.items())),
            "field_match_kinds": dict(sorted(self.field_match_kinds.items())),
            "consistent": self.consistent,
            "covered": self.covered,
            "sound": self.sound,
            "base_mismatch": {k: list(v) for k, v in self.base_mismatch.items()},
            "offset_mismatch": {k: list(v)
                                for k, v in self.offset_mismatch.items()},
            "bits_mismatch": {k: list(v)
                              for k, v in self.bits_mismatch.items()},
            "registers_not_modeled": [list(x)
                                      for x in self.registers_not_modeled],
            "structural_exempt": {k: sorted(v)
                                  for k, v in self.structural_exempt.items()},
            "structural_unresolved": dict(sorted(
                self.structural_unresolved.items())),
            "bits_not_modeled": self.bits_not_modeled,
            "bits_unresolved": self.bits_unresolved,
            "bits_ambiguous": self.bits_ambiguous,
            "peripherals_without_struct": self.peripherals_without_struct,
            "unmapped": self.unmapped,
            "no_instance": self.no_instance,
            "skipped_core": self.skipped_core,
            "structs_with_conditionals": self.structs_with_conditionals,
            "known_hits": self.known_hits,
            "known_stale": self.known_stale,
        }


def _register_offset(members: dict[str, int], register: str, peripheral: str,
                     group: str) -> tuple[str | None, int | None]:
    """在结构体成员里找同名寄存器。返回 ``(命中的成员名, 偏移)``。

    SVD 对部分外设把前缀写进寄存器名（`FDCAN_CCCR`），器件头成员是裸名，
    所以先试原名、再试剥了外设/组前缀的形式。
    """
    for variant in (register, register[len(peripheral) + 1:]
                    if peripheral and register.startswith(peripheral + "_")
                    else None,
                    register[len(group) + 1:]
                    if group and register.startswith(group + "_") else None):
        if variant and variant in members:
            return variant, members[variant]
    return None, None


def compare_stm32(svd_path: Path | str, header_path: Path | str,
                  *, mcu: str = "stm32h743zit6") -> Stm32Parity:
    """SVD ↔ 器件头 比对。"""
    from firmforge.knowledge.extractors import stm32_devheader as dev
    from firmforge.knowledge.extractors import stm32_registers as ex32

    svd_path, header_path = Path(svd_path), Path(header_path)
    header = dev.parse_device_header(header_path)
    parsed = ex32.parse_svd(svd_path)

    rep = Stm32Parity(mcu=mcu, svd=svd_path.name, header=header.path,
                      parser_version=dev.PARSER_VERSION)
    rep.header_instances = len(header.instances)
    rep.header_macros = len(header.macros)
    rep.structs_with_conditionals = list(header.structs_with_conditionals)

    hits: set[tuple[str, str, str, str]] = set()

    def _adjudicate(pn: str, rn: str, kind: str, fld: str,
                    svd_val: int, hdr_val: int,
                    sink: dict[str, tuple[int, int]], label: str) -> None:
        """值不同：命中已知缺陷表就消掉，否则记冲突。"""
        for ki in STM32_KNOWN_ISSUES:
            if ki.covers(pn, rn, kind, fld) and ki.matches(svd_val, hdr_val):
                hits.add(ki.key)
                if ki.describe() not in rep.known_hits:
                    rep.known_hits.append(ki.describe())
                return
        sink[label] = (svd_val, hdr_val)

    def _bit_shift_rule(pn: str, rn: str) -> KnownIssue | None:
        """整寄存器位号偏移型缺陷（`BDMA.ISR/IFCR`）。"""
        for ki in STM32_KNOWN_ISSUES:
            if ki.kind == "bit_shift" and ki.covers(pn, rn, "bit_shift"):
                return ki
        return None

    for per in parsed["peripherals"]:
        pn = per["name"]
        group = per.get("group_name", "")
        rep.svd_peripherals += 1

        inst_name, how = dev.map_peripheral(header, pn)
        if inst_name is None:
            bucket = {"core": rep.skipped_core,
                      "no_instance": rep.no_instance}.get(how)
            (bucket if bucket is not None else rep.unmapped).append(pn)
            continue
        rep.mapped_peripherals += 1
        rep.match_kinds[how] = rep.match_kinds.get(how, 0) + 1

        # 器件头实例基址 + 该段在实例内的起始偏移 = 这一段的真实基址
        base_shift = STRUCTURAL_BASE_OFFSET.get(pn, 0)
        header_base = header.base_address(inst_name)
        if header_base is not None and header_base + base_shift != per["base_address"]:
            _adjudicate(pn, "<base>", "base", "", per["base_address"],
                        header_base + base_shift, rep.base_mismatch, pn)

        struct = header.instances[inst_name].struct
        members = header.members(struct)
        has_struct = bool(header.structs.get(struct))
        if not has_struct:
            rep.peripherals_without_struct.append(pn)

        # 建模粒度不同的外设：结构体里找不到对等物的寄存器进豁免表。
        # **只豁免"找不到"这一种**，寄存器名对得上的仍然照比 ——
        # BDMA 既是"通道寄存器被拉平"（结构性），又藏着 ISR/IFCR 的位号
        # 整体偏移缺陷（真错）。整外设跳过会把真缺陷一起藏掉。
        structural = pn in STRUCTURAL_DIFFERENCES

        for reg in per["registers"]:
            rn = reg["name"]
            rep.svd_registers += 1
            member, member_off = _register_offset(members, rn, pn, group)
            if member is None:
                if structural:
                    rep.structural_exempt.setdefault(pn, []).append(rn)
                elif has_struct:
                    rep.registers_not_modeled.append((pn, rn))
                continue
            rep.registers_matched += 1

            # 比绝对地址：SVD 会把一个器件头外设拆成几段，各段基址不同
            svd_abs = per["base_address"] + reg["offset"]
            hdr_abs = (header_base or 0) + member_off
            if header_base is not None and hdr_abs != svd_abs:
                _adjudicate(pn, rn, "offset", "", svd_abs, hdr_abs,
                            rep.offset_mismatch, f"{pn}.{rn}")

            shift = _bit_shift_rule(pn, rn)
            for f in reg.get("fields", []):
                fn, bit = f["name"], f["bit"]
                rep.svd_fields += 1
                if shift is not None:
                    # 整寄存器偏移型缺陷：按规则判定，个例不再进位域查找
                    hits.add(shift.key)
                    if shift.describe() not in rep.known_hits:
                        rep.known_hits.append(shift.describe())
                    rep.fields_matched += 1
                    continue

                value, how_f = header.lookup_field(member, fn, inst_name, pn,
                                                   group)
                if how_f == "none":
                    if structural:
                        # 该外设的建模粒度本就与 SVD 不同，位域名对不上是
                        # 预期内的，理由已由 STRUCTURAL_DIFFERENCES 记着
                        rep.structural_unresolved.setdefault(pn, 0)
                        rep.structural_unresolved[pn] += 1
                    elif header.has_pos_macros(member, rn):
                        rep.bits_unresolved.append(f"{pn}.{rn}.{fn}")
                    else:
                        rep.bits_not_modeled.append(f"{pn}.{rn}.{fn}")
                    continue
                if how_f == "ambiguous":
                    rep.bits_ambiguous.append(f"{pn}.{rn}.{fn}")
                    continue
                rep.field_match_kinds[how_f] = (
                    rep.field_match_kinds.get(how_f, 0) + 1)
                if value == bit:
                    rep.fields_matched += 1
                else:
                    _adjudicate(pn, rn, "bit", fn, bit, value,
                                rep.bits_mismatch, f"{pn}.{rn}.{fn}")

    rep.known_stale = [k.describe() for k in STM32_KNOWN_ISSUES
                       if k.key not in hits]
    return rep


#: 本机 STM32 知识库覆盖的器件 —— mcu → (SVD 文件名, 器件头文件名)。
STM32_DEVICES: dict[str, tuple[str, str]] = {
    "stm32h743zit6": ("STM32H743x.svd", "stm32h743xx.h"),
}


def find_svd(name: str, series: str | None = None) -> Path:
    """SVD 的取用路径：B 区 `cache/knowledge/_sources/<系列>/`。

    SVD 是**下载来的厂商物**（删了重新下载即可），按路径分区标准属 B 区，
    不该进 A 区；也**不该住在 `.ff-run/`** —— 那个目录是运行时，
    整块删除是它的正常用法，把它当厂家物的仓库会让「能不能删」失去答案
    （曾经就有一份 3.9 MB 的 SVD 副本躺在 `.ff-run/probe/` 里）。

    **按系列分目录**：一份 SVD 只描述一个系列（H743 的 SVD 与 F103 的
    毫无关系），平铺在一个 `_sources/` 下时，型号一多就分不清哪份属于哪代。
    旧版平铺位置仍作为兜底查找，便于老环境直接跑通（下次生成即迁到新位置）。

    生成器（`stm32_registers`）与比对器共用这一份定位逻辑 —— 两处各写
    一遍会漂移成「报告能找到源、生成器找不到」。

    Returns:
        路径（**可能不存在**，调用方用 ``is_file()`` 判定）。
    """
    from firmforge.infrastructure import paths
    root = paths.knowledge_cache_dir() / "_sources"
    candidates = ([root / series.strip().lower() / name] if series else [])
    candidates.append(root / name)          # 旧版平铺位置，兼容已装环境
    return next((p for p in candidates if p.is_file()), candidates[0])


def default_cmsis_include() -> Path:
    """本机 CMSIS 器件头所在目录（B 区 packages，随 `ff setup` 安装）。"""
    from firmforge.infrastructure import paths
    return (paths.packages_dir() / "stm32" / "cmsis_device_h7" / "1.10.7"
            / "Include")


def compare_stm32_all(repo_root: Path,
                      include_dir: Path | None = None
                      ) -> list[Stm32Parity]:
    """比对本机全部 STM32 器件。SVD 或器件头缺失时跳过（不抛异常）。"""
    repo_root = Path(repo_root)
    include_dir = include_dir or default_cmsis_include()
    out: list[Stm32Parity] = []
    for mcu, (svd_name, header_name) in STM32_DEVICES.items():
        from firmforge.knowledge.platforms import device_series
        svd = find_svd(svd_name, device_series(None, mcu))
        header = Path(include_dir) / header_name
        if not svd.is_file() or not header.is_file():
            continue
        out.append(compare_stm32(svd, header, mcu=mcu))
    return out


def _top_by_prefix(items: list[str], limit: int) -> list[tuple[str, int]]:
    """把 `外设.寄存器.位域` 列表按外设汇总排序（报告只给头部，别糊一屏）。"""
    counts: dict[str, int] = {}
    for it in items:
        counts[it.split(".", 1)[0]] = counts.get(it.split(".", 1)[0], 0) + 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]


def render_stm32_text(reports: list[Stm32Parity]) -> str:
    """STM32 比对的人类可读报告。"""
    lines: list[str] = []
    for rep in reports:
        lines.append("=" * 72)
        lines.append(f"{rep.mcu}  (SVD: {rep.svd} ↔ 器件头: {rep.header})")
        lines.append(f"  解析器:     {rep.parser_version}")
        lines.append(f"  外设:       SVD {rep.svd_peripherals} / "
                     f"映射到器件头 {rep.mapped_peripherals}")
        lines.append(f"  寄存器:     SVD {rep.svd_registers} / "
                     f"器件头结构体对上 {rep.registers_matched}")
        lines.append(f"  位域:       SVD {rep.svd_fields} / "
                     f"器件头解析对上 {rep.fields_matched}")
        lines.append(f"  外设映射:   "
                     + " ".join(f"{k}={v}"
                                for k, v in sorted(rep.match_kinds.items())))
        lines.append(f"  位域解析:   "
                     + " ".join(f"{k}={v}" for k, v in
                                sorted(rep.field_match_kinds.items())))
        lines.append(f"  一致性:     "
                     f"{'OK' if rep.consistent else '有同名不同值 → 需人工裁定'}")
        lines.append(f"  覆盖性:     "
                     f"{'OK' if rep.covered else '有找不到对等物 → 需人工裁定'}")
        lines.append(f"  已知缺陷表: 命中 {len(rep.known_hits)} 条"
                     + (f"，**失效 {len(rep.known_stale)} 条**"
                        if rep.known_stale else "，无失效"))
        if rep.structs_with_conditionals:
            lines.append(f"  ⚠ 含预处理器分支的结构体: "
                         f"{rep.structs_with_conditionals}")

        def _dump(title: str, items: list, limit: int = 15) -> None:
            if not items:
                return
            lines.append(f"  {title} ({len(items)}):")
            for it in items[:limit]:
                lines.append(f"    - {it}")
            if len(items) > limit:
                lines.append(f"    … 其余 {len(items) - limit} 条")

        _dump("基址不一致（SVD vs 器件头）",
              [f"{k}: 0x{a:X} vs 0x{b:X}"
               for k, (a, b) in rep.base_mismatch.items()])
        _dump("绝对地址不一致（SVD vs 器件头结构体）",
              [f"{k}: 0x{a:X} vs 0x{b:X}"
               for k, (a, b) in rep.offset_mismatch.items()])
        _dump("位号不一致（SVD vs 器件头 _Pos）",
              [f"{k}: {a} vs {b}"
               for k, (a, b) in rep.bits_mismatch.items()])
        _dump("SVD 有、器件头未建模（寄存器，非错误）", rep.registers_not_modeled)
        _dump("位域在器件头里对不上名（命名口径）", rep.bits_unresolved)
        _dump("位域在器件头里没有对应宏（器件头未建模）",
              rep.bits_not_modeled)
        _dump("位域解析出多个值（歧义）", rep.bits_ambiguous)
        _dump("器件头无结构体（只能比基址）", rep.peripherals_without_struct)
        _dump("未映射到器件头实例", rep.unmapped)
        _dump("器件头无实例指针（非内核）", rep.no_instance)
        _dump("内核外设（不在器件头管辖）", rep.skipped_core)

        if rep.structural_exempt or rep.structural_unresolved:
            total = sum(len(v) for v in rep.structural_exempt.values())
            bits = sum(rep.structural_unresolved.values())
            lines.append(f"  结构性差异（已裁定，不计入缺失）："
                         f"{len(rep.structural_exempt)} 个外设 / "
                         f"{total} 个寄存器 / {bits} 个位域名对不上")
            for pn in sorted(set(rep.structural_exempt)
                             | set(rep.structural_unresolved)):
                lines.append(f"    · {pn} (寄存器 {len(rep.structural_exempt.get(pn, []))}、"
                             f"位域 {rep.structural_unresolved.get(pn, 0)}): "
                             f"{STRUCTURAL_DIFFERENCES.get(pn, '')}")
        if rep.bits_unresolved:
            lines.append("  ⚠ 命名口径未登记的外设（生成知识库时的**取名依据**："
                         "这些位域要取器件头的宏名，不能取 SVD 名）:")
            for pn, n in _top_by_prefix(rep.bits_unresolved, 12):
                lines.append(f"    - {pn}: {n} 个位域")
        if rep.known_hits:
            lines.append(f"  已裁定 SVD 缺陷（{len(rep.known_hits)}）:")
            for it in rep.known_hits:
                lines.append(f"    · {it}")
        if rep.known_stale:
            lines.append(f"  ⚠ 已知缺陷表失效（{len(rep.known_stale)}）——"
                         f"值已变，须重新裁定:")
            for it in rep.known_stale:
                lines.append(f"    ! {it}")
    lines.append("=" * 72)
    return "\n".join(lines)
