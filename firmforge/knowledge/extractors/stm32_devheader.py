"""CMSIS 器件头（`stm32h743xx.h`）→ 第二来源结构。

为什么需要它
------------
`stm32_registers.py` 只吃 SVD。SVD 是厂商的机器可读描述，但它**会错** ——
本机实测三处（见 `parity.py` 的 `STM32_KNOWN_ISSUES`）：

* `CRC`：SVD 漏掉 `0x0C` 的保留字，`INIT`/`POL` 整体前移 4 字节；
* `MDIOS`：SVD 漏掉 `DINR0` 前 57 个字的保留区，`DINR0` 从 `0x1C` 说起
  （器件头/单片机手册都是 `0x100`）；
* `BDMA.ISR`：SVD 少了整组通道 0 的位域，`GIF1` 被放到 bit 0
  （器件头是 bit 4）——**位号错位**是最危险的一类，写代码必错。

器件头是**编译器真正吃的那份**：结构体成员决定 `GPIOA->MODER` 落在哪个
地址，`_Pos` 宏决定 `(1U << USART_CR1_UE_Pos)` 落在哪一位。所以
「与器件头一致」= 「与工具链将要编译出的机器码一致」，这是比"两个都是
ST 出的所以算同源"更硬的一条轴。**两者都由 ST 生成，不构成完全独立的
证据链**；真正的独立性来自它们是**两条不同的生成管线 + 两种不同的表示**
（XML 属性 vs 结构体布局 + 宏），足以暴露单边笔误。

三样东西怎么取
--------------
1. **实例指针** `#define GPIOA ((GPIO_TypeDef *) GPIOA_BASE)`
   → 外设名到结构体类型的映射，也给出基址宏名。
2. **结构体成员** `typedef struct { __IO uint32_t MODER; ... } GPIO_TypeDef;`
   → 成员名即寄存器名（与 SVD 同源，应字面相同），累计宽度即偏移。
   H743 头里成员类型只有 `__IO uint32_t` / `__I uint32_t` 两种（1075/7），
   无匿名 union、无嵌套 —— 所以累计宽度不会错。
3. **位域宏** `#define GPIO_MODER_MODER0_Pos (0U)`
   → 反查表的键取**宏名的尾部** `(寄存器, 位域)`，值取位号。

   这里不能靠"重建宏名"：宏前缀既不是外设名也不是 SVD 的 groupName ——
   `COMP1` 用 `COMP_`、`Ethernet_MAC` 用 `ETH_`、`TIM16` 用 `TIM_`，
   而且 FDCAN1 的 SVD 寄存器名自带前缀（`FDCAN_CCCR`），器件头不带。
   取尾部做键天然绕过这两层命名差异。

为什么基址宏可以脱离编译器求值
------------------------------
本机 286 个 `*_BASE` 宏只有三种形态：字面量 `(0x40000000UL)`、
父+偏移 `(PERIPH_BASE + 0x2400UL)`、裸引用 `PERIPH_BASE`。
递归展开即可，不需要 `arm-none-eabi-gcc -E`（也就不需要工具链在场）。
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path

#: 解析器版本 —— 参与报告留痕。**改解析逻辑必须递增它**。
PARSER_VERSION = "stm32-devheader/1.0.0"

#: 行连接符拼接：`#define` 的续行在宏表里要拼成一行。
_CONT = re.compile(r"\\\n\s*")

#: 实例指针：`#define GPIOA ((GPIO_TypeDef *) GPIOA_BASE)`。
#: 后缀必须写 `\w*TypeDef` 而不是 `_TypeDef` —— H743 里有
#: `USB_OTG_GlobalTypeDef` / `FDCAN_GlobalTypeDef` / `ADC_Common_TypeDef`，
#: 只认 `_TypeDef` 会漏掉 20 个外设（曾实测）。
_INSTANCE = re.compile(
    r"^#define\s+([A-Za-z_]\w*)\s+\(\(\s*([A-Za-z0-9_]+TypeDef)\s*\*+\s*\)"
    r"\s*([A-Za-z_]\w*)\s*\)",
    re.M,
)

#: 结构体：`typedef struct { ... } XXX_TypeDef;`（非贪婪，配合 re.S）
_STRUCT = re.compile(r"typedef\s+struct\s*\{(.*?)\}\s*([A-Za-z0-9_]+TypeDef)\s*;",
                     re.S)

#: 结构体成员。`__IO`/`__I` 可选，数组记基数并计入总宽。
_MEMBER = re.compile(
    r"^\s*(?:__IO|__I|__O|__IM)?\s*(uint8_t|uint16_t|uint32_t|int8_t|int16_t"
    r"|int32_t)\s+([A-Za-z_]\w*)\s*(?:\[\s*(\d+)\s*\])?\s*;"
)

#: 位域宏：`#define XXX_YYY_ZZZ_Pos (0U)` / `(0x10U)`
_POS = re.compile(r"^#define\s+([A-Za-z_]\w*)_Pos\s+"
                  r"\(\s*(0[xX][0-9A-Fa-f]+|\d+)\s*U?\s*\)", re.M)

#: 位域掩码：`#define XXX_YYY_ZZZ_Msk (0x3FFUL << XXX_YYY_ZZZ_Pos)`。
#: 用来求位域**宽度** —— 宽度是判断「SVD 是不是把整字段拆成了单 bit」的依据。
_MSK = re.compile(r"^#define\s+([A-Za-z_]\w*)_Msk\s+"
                  r"\(\s*(0[xX][0-9A-Fa-f]+|\d+)\s*U?L*\s*<<", re.M)

#: 普通宏（用于基址求值）。**对象式宏的定义是「名字后面必须有空白」**——
#: C 预处理器就是这么区分对象式宏与函数式宏的。早先用 `\s+(?!\()` 写，
#: 在「名字后只有一个空格、紧跟 `(`」时会被负向前瞻判成函数式宏而漏掉
#: （`RAMECC1_Monitor1_BASE (RAMECC1_BASE + 0x20UL)` 实测 12 条全漏）。
_PLAIN_MACRO = re.compile(r"^#define[ \t]+([A-Za-z_]\w*)[ \t]+([^\n]*)", re.M)

_INT_LITERAL = re.compile(r"^0[xX][0-9A-Fa-f]+$|^\d+$")


@dataclass
class Instance:
    """一条实例指针宏。"""

    name: str
    struct: str
    base_macro: str


@dataclass
class Member:
    """结构体成员 —— 偏移由前序成员累计得出。"""

    name: str
    offset: int
    size: int


@dataclass
class DeviceHeader:
    """器件头解析结果。"""

    path: str
    macros: dict[str, str] = field(default_factory=dict)
    instances: dict[str, Instance] = field(default_factory=dict)
    structs: dict[str, list[Member]] = field(default_factory=dict)
    #: (寄存器名, 位域名) -> {宏名: 位号}（精确）
    field_pos: dict[tuple[str, str], dict[str, int]] = field(default_factory=dict)
    #: 同上，键去掉下划线并大写（兜底）
    field_pos_norm: dict[tuple[str, str], dict[str, int]] = field(
        default_factory=dict)
    #: 在某个位域宏里出现过的寄存器名片段 —— 用来判断「器件头有没有为
    #: 这个寄存器定义位域宏」，与「宏名对不上」区分开
    regs_with_pos_macros: set[str] = field(default_factory=set)
    #: 位域宏名（去掉 `_Msk`）→ 位宽（掩码里 1 的个数）
    field_width: dict[str, int] = field(default_factory=dict)
    #: 含预处理器分支的结构体名 —— 累加宽度在这些上可能不可靠，必须报告
    structs_with_conditionals: list[str] = field(default_factory=list)
    parse_ms: float = 0.0

    # -- 基址 -------------------------------------------------------------

    def base_address(self, peripheral: str) -> int | None:
        """外设基址 —— 沿 `*_BASE` 宏递归求值。"""
        inst = self.instances.get(peripheral)
        if inst is None:
            return None
        return self.resolve_macro(inst.base_macro)

    def resolve_macro(self, name: str, depth: int = 0) -> int | None:
        """把宏求成整数。字面量 / `A + B` / 裸引用 三种形态。

        不能用 `int(body)` —— SVD 那边 `size` 踩过同样的坑（写成十六进制）。
        这里 `_BASE` 宏体还带 `UL` 后缀与括号，更要显式剥。

        注意左操作数是宏名、右操作数是**字面量**（`PERIPH_BASE + 0x2400UL`），
        所以求值入口必须同时接受两者 —— 早先只查宏表，右操作数查不到就
        整条返回 None（实测 286 个基址全数失效）。
        """
        return self._eval(self.macros.get(name, name), depth)

    def _eval(self, expr: str, depth: int) -> int | None:
        """对**表达式文本**求值。"""
        if depth > 12:
            return None
        expr = expr.split("/*")[0].strip()
        expr = expr.strip().strip("()").strip()
        expr = re.sub(r"(?<=[0-9A-Fa-f])U?L+$", "", expr, flags=re.I)
        if not expr:
            return None

        if _INT_LITERAL.match(expr):
            return int(expr, 0)

        plus = _split_plus(expr)
        if plus is not None:
            left = self._eval(plus[0].strip(), depth + 1)
            right = self._eval(plus[1].strip(), depth + 1)
            if left is None or right is None:
                return None
            return left + right

        if re.match(r"^[A-Za-z_]\w*$", expr):
            if expr not in self.macros:
                return None
            return self._eval(self.macros[expr], depth + 1)
        return None

    # -- 查询 -------------------------------------------------------------

    def member_offset(self, struct: str, name: str) -> int | None:
        """结构体里同名成员的偏移。"""
        for m in self.structs.get(struct, ()):
            if m.name == name:
                return m.offset
        return None

    def members(self, struct: str) -> dict[str, int]:
        """结构体的「非保留成员 → 偏移」表。"""
        return {m.name: m.offset for m in self.structs.get(struct, ())
                if not m.name.startswith("RESERVED")}

    # -- 位域 -------------------------------------------------------------

    def has_pos_macros(self, *register_names: str) -> bool:
        """器件头有没有为这个寄存器定义过位域宏。

        用来把「器件头根本不建模这个寄存器的位」与「宏名对不上」区分开 ——
        前者是覆盖性事实，后者是命名口径，两者的处理方式不同。
        """
        have = {_norm(r) for r in self.regs_with_pos_macros}
        return any(_norm(r) in have for r in register_names if r)

    def lookup_field(self, register: str, field: str, instance: str,
                     peripheral: str, group: str
                     ) -> tuple[int | None, str]:
        """查位域位号。返回 ``(位号或 None, 解析方式)``。

        解析方式（按序尝试，先命中的为准）：

        ``exact``   精确键 + 实例前缀筛选 —— 主路径
        ``norm``    归一化键（去下划线、大写）—— 兜底命名差异
                     （SVD `I2C1FMP` vs 器件头 `I2C1_FMP`）
        ``digit``   归一化键 + 去尾随编号，**且命中的位域必须是单 bit** ——
                     兜底 bank/channel 编号差异（SVD `FLASH.CR1.LOCK1`
                     vs 器件头 `FLASH_CR1_LOCK`）。
                     单 bit 这个限制不能省：SVD 会把 `I2C_CR2.SADD` 这样的
                     10 位字段**逐个 bit 展开**成 `SADD1..SADD9`，不限制就会
                     把它们全对上那个宽度 10 的整体字段、报出 9 条假冲突
                     （实测 157 条里的绝大多数）。
        ``prefix``  精确键的**词边界前缀**匹配（SVD `ISR.RXNE` vs 器件头
                     `USART_ISR_RXNE_RXFNE`）。放最后，因为区分度最低。
                     必须是「整段前缀」：`TEFL` **不能**匹配 `TEFLL`
                     （那是一位转置、量级完全不同的两个字段），
                     只能匹配 `TEFL_XXX` 这种在后面加词的形式。
        ``numbered`` 同寄存器 + **尾随编号相同**（SVD `MODE0` vs 器件头
                     `MODER0`；SVD `PUPDR0` vs 器件头 `PUPD0`）。只兜
                     拼法差异，不兜语义差异 —— 编号不带的字段不参与，
                     所以 SVD 逐位展开的 `SADD1..9` 不会被配到 `SADD`。
        ``none``    查不到
        ``ambiguous`` 查到多值且实例前缀筛不掉 —— 真的判不了，必须报告

        先精确后归一、先带编号后去编号，顺序不能换：归一化与去编号都会
        降低区分度，只配当兜底。

        **不做「全体候选兜底」**：早先实例前缀筛空时会退回全局池，结果
        `FLASH.CR2.START2` 被别的外设的 `I2C_CR2_START`（bit 13）对上，
        报成冲突。宁可返回 `none`（进"命名口径未登记"清单，看得见），
        也不能拿别的外设的位号充数。
        """
        macro, bit, stage = self._lookup(register, field, instance,
                                         peripheral, group)
        return (bit, stage) if macro else (None, stage)

    def lookup_field_macro(self, register: str, field: str, instance: str,
                           peripheral: str, group: str
                           ) -> tuple[str | None, int | None, str]:
        """同 `lookup_field`，但同时给出**器件头里的宏基名**。

        生成知识库用的是它：源码里出现的是 `GPIO_MODER_MODER0_Pos`，
        所以数据里要记 `GPIO_MODER_MODER0`（`_Pos` 已由解析器剥掉），
        而不是 SVD 的叫法 `MODE0`。SVD 名另存 `svd_name` 供回溯。
        """
        return self._lookup(register, field, instance, peripheral, group)

    def _lookup(self, register: str, field: str, instance: str,
                peripheral: str, group: str
                ) -> tuple[str | None, int | None, str]:
        """四级档主循环，返回 ``(宏基名, 位号, 方式)``。

        单拆一个方法，是为了让「查位号」与「查宏名」共用同一套档位与去重
        规则 —— 两处各写一遍必然漂移（先例：GCC 诊断解析曾 avr/arm 各一份）。
        """
        for stage in ("exact", "norm", "digit", "prefix", "numbered"):
            index = (self.field_pos if stage in ("exact", "prefix", "numbered")
                     else self.field_pos_norm)
            keys = [(r, f)
                    for r in _reg_keys(register, peripheral, group, stage)
                    for f in _field_keys(field, stage)]
            if stage in ("norm", "digit"):
                keys = [(_norm(r), _norm(f)) for r, f in keys]
            for key in dict.fromkeys(keys):        # 去重且保序
                cands = self._pool(index, key, stage, instance,
                                   peripheral, group)
                if not cands:
                    continue
                if len(cands) == 1:
                    return cands[0][0], cands[0][1], stage
                return None, None, "ambiguous"
        return None, None, "none"

    def _pool(self, index: dict, key: tuple[str, str], stage: str,
              instance: str, peripheral: str, group: str
              ) -> list[tuple[str, int]]:
        """取该键下、属于本外设、且通过档位约束的位域 ``(宏基名, 位号)``。

        **按位号去重，不按宏名**：同一个 bit 常挂两个宏名
        （`USART_ISR_RXNE` 与 `USART_ISR_RXNE_RXFNE` 是同一位的两种叫法）。
        若按宏名计数，`len(cands) == 1` 这个「唯一命中」判定会凭空变严，
        把原本唯一的命中报成 `ambiguous`。同一位号取**最短**宏名 ——
        最短的通常是没有附加模式后缀的本名。
        """
        if stage == "prefix":
            # 词边界前缀：`ISR.RXNE` 要找 `ISR.RXNE_RXFNE`，但 `ISR.TEFL`
            # 不能找 `ISR.TEFLL`（后者是一位转置，不是加词）。
            want = key[1].split("_")
            cands = {n: v
                     for k, mm in index.items() if k[0] == key[0]
                     for n, v in mm.items()
                     if _is_token_prefix(want, k[1].split("_"))}
        elif stage == "numbered":
            # 同寄存器、**尾随编号相同**且**基名互为前缀**的位域。
            # 只兜拼法差异，不兜语义差异：
            #   SVD `MODE0`   ↔ 器件头 `MODER0`   （MODER 以 MODE 开头）✓
            #   SVD `PUPDR0`  ↔ 器件头 `PUPD0`    （PUPDR 以 PUPD 开头）✓
            #   SVD `DEDT0`   ↔ 器件头 `M0`       （DEDT / M 无前缀关系）✗
            # 最后一条实测会误配到 bit 12（M0 是 USART 的字长位），所以
            # 「基名互为前缀 + 短者至少 3 字符」是硬约束，不能省。
            want_num = re.search(r"(\d+)$", key[1])
            if want_num is None:
                return []
            num = want_num.group(1)
            want_base = key[1][:want_num.start()]
            if len(want_base) < 3:
                return []
            cands = {}
            for k, mm in index.items():
                if k[0] != key[0]:
                    continue
                m = re.search(r"(\d+)$", k[1])
                if not m or m.group(1) != num:
                    continue
                base = k[1][:m.start()]
                if (len(base) >= 3
                        and (base.startswith(want_base)
                             or want_base.startswith(base))):
                    cands.update(mm)
        else:
            cands = index.get(key, {})
        scoped = {n: v for n, v in cands.items()
                  if scope_match(n, instance, peripheral, group)}
        if not scoped:
            return []
        if stage == "digit":
            # 只认单 bit 字段（理由见 docstring）
            scoped = {n: v for n, v in scoped.items()
                      if self.field_width.get(n, 1) == 1}
        best: dict[int, str] = {}
        for macro, bit in sorted(scoped.items(),
                                 key=lambda kv: (len(kv[0]), kv[0])):
            best.setdefault(bit, macro)
        return sorted(((m, b) for b, m in best.items()), key=lambda x: x[1])


def _split_plus(expr: str) -> tuple[str, str] | None:
    """在**顶层**加号处切分 `A + B`（跳过括号内的加号）。"""
    depth = 0
    for i, ch in enumerate(expr):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "+" and depth == 0:
            return expr[:i], expr[i + 1:]
    return None


def _parse_structs(text: str) -> tuple[dict[str, list[Member]], list[str]]:
    """解析全部结构体，返回 ``(类型名 → 成员表, 含条件编译的名单)``。

    偏移用**累计**而不是"数成员 × 4"：H743 头里所有成员确实都是 4 字节，
    但一旦官方加了 `uint16_t` 或数组，硬编码步长就会静默算错。
    """
    structs: dict[str, list[Member]] = {}
    conditional: list[str] = []
    for m in _STRUCT.finditer(text):
        body, tname = m.group(1), m.group(2)
        if "#if" in body or "#ifdef" in body or "#else" in body:
            # 有分支时累加宽度会失真 —— 记下来，让报告显式说明，
            # 不静默按某一支算（对齐 AVR 侧 conditional_filter 的留痕原则）。
            conditional.append(tname)
        members: list[Member] = []
        seen: set[str] = set()
        off = 0
        for line in body.splitlines():
            mm = _MEMBER.match(line)
            if not mm:
                continue
            bits = int(re.search(r"(\d+)", mm.group(1)).group(1))
            width = bits // 8
            count = int(mm.group(3)) if mm.group(3) else 1
            size = width * count
            name = mm.group(2)
            if name in seen:
                # 同名重复只可能来自未识别干净的分支，跳过重复项避免双算
                continue
            seen.add(name)
            members.append(Member(name=name, offset=off, size=size))
            off += size
        structs[tname] = members
    return structs, conditional


def _norm(text: str) -> str:
    """归一化键：只留字母数字并大写。

    SVD 与器件头对同一个位域可能只差下划线位置
    （SVD `SYSCFG.PMCR.I2C1FMP` vs 器件头 `SYSCFG_PMCR_I2C1_FMP`），
    抹掉分隔符即可对上。**归一化只是兜底**，精确匹配永远先走。
    """
    return re.sub(r"[^A-Za-z0-9]", "", text).upper()


def _reg_keys(register: str, peripheral: str, group: str, stage: str
              ) -> list[str]:
    """寄存器名的候选键。

    先剥外设/组前缀（SVD `FDCAN_CCCR` → 器件头成员 `CCCR`），
    `digit` 档再额外去掉尾随编号（SVD `KEYR1` → 器件头 `KEYR`）。
    """
    out = [register]
    for pfx in (peripheral, group):
        if pfx and register.startswith(pfx + "_"):
            out.append(register[len(pfx) + 1:])
    if stage == "digit":
        out += [re.sub(r"\d+$", "", r) for r in out]
    return out


def _field_keys(field: str, stage: str) -> list[str]:
    """位域名的候选键。`digit` 档去掉尾随编号（SVD `LOCK1` → 器件头 `LOCK`）。"""
    out = [field]
    if stage == "digit":
        out.append(re.sub(r"\d+$", "", field))
    return out


def _is_token_prefix(want: list[str], have: list[str]) -> bool:
    """`have` 是否以 `want` 整段开头且更长。

    `["RXNE"] → ["RXNE","RXFNE"]` ✓ ；`["TEFL"] → ["TEFLL"]` ✗。
    后者看起来也"以 TEFL 开头"，但它是**一位转置**（bit 11 ↔ bit 15），
    不是同一个字段的加长写法 —— 不加词边界就会报出假冲突（实测踩过）。
    """
    return len(have) > len(want) and have[:len(want)] == want


def scope_match(macro: str, instance: str, peripheral: str,
                group: str) -> bool:
    """位域宏名是否属于这个外设。

    同一个位域名会在多个外设出现且位号不同（`DMA_ISR_GIF1` 与
    `BDMA_ISR_GIF1`），所以解析出名字后要按实例前缀再筛一次。

    候选前缀含**去掉尾部数字**的形式：器件头的宏用族名
    （`DMA_`/`TIM_`/`GPIO_`），SVD 的实例名带编号（`DMA1`/`TIM2`）。
    另外再按**归一化**比一次，覆盖大小写差异（SVD `Flash` vs 器件头 `FLASH_`）。

    少了归一化这一路会出事：`FLASH.CR2.START2` 的实例前缀是 `Flash`，
    匹配不上 `FLASH_`，于是筛空 → 退回全局池 → 被别的外设的
    `I2C_CR2_START`（bit 13）对上，报成假冲突。

    还要走 `PREFIX_ALIASES`：H743 器件头里**一个 `LPUART_*` 宏都没有**
    （实测 0 条），LPUART1 靠 `USART_TypeDef` 与 `USART_*` 宏访问。
    不加别名，LPUART1 的 89 个位域会全部掉进"命名口径未登记"。
    """
    prefixes = {instance, peripheral, group}
    prefixes |= {p.rstrip("0123456789") for p in tuple(prefixes) if p}
    prefixes |= {a for p in tuple(prefixes) for a in PREFIX_ALIASES.get(p, ())}
    normalized = _norm(macro)
    return any(macro.startswith(p + "_")
               or normalized.startswith(_norm(p) + "_")
               for p in prefixes if p)


def _parse_field_pos(text: str
                     ) -> tuple[dict[tuple[str, str], dict[str, int]],
                                dict[tuple[str, str], dict[str, int]],
                                set[str],
                                dict[str, int]]:
    """位域宏 → 四份索引。

    返回 ``(精确索引, 归一化索引, 有宏的寄存器名集合, 宏名 → 位宽)``。

    精确索引键 = 宏名**尾部**的每一个切分点（除首段）：前缀不可预测，
    取尾部天然绕过 `COMP1`→`COMP_`、`Ethernet_MAC`→`ETH_`、
    `TIM16`→`TIM_` 这些前缀差异。

    归一化索引同构，只是键去掉了下划线。**它只在精确索引查不到时才用** ——
    归一化必然降低区分度，不能当主路径。

    「有宏的寄存器名集合」用来区分两件不同的事：
    * 寄存器压根没有位域宏（器件头未建模它的位）→ 信息，不是错；
    * 有宏但这个名字对不上 → 命名口径，要登记。

    位宽来自 `_Msk`（掩码里 1 的个数），用途见 `lookup_field` 的
    `digit` 档说明。
    """
    exact: dict[tuple[str, str], dict[str, int]] = {}
    norm: dict[tuple[str, str], dict[str, int]] = {}
    regs: set[str] = set()
    for m in _POS.finditer(text):
        whole = m.group(1)
        value = int(m.group(2), 0)
        parts = whole.split("_")
        for i in range(1, len(parts) - 1):
            reg, fld = parts[i], "_".join(parts[i + 1:])
            exact.setdefault((reg, fld), {})[whole] = value
            norm.setdefault((_norm(reg), _norm(fld)), {})[whole] = value
            # 每个切分点的首段都可能是寄存器名（`RTC_OR_OUT_RMP` 里 `OR` 是
            # 寄存器、`OUT` 是位域的一部分，光看宏名分不出），所以全收进集合。
            # 这个集合只用来回答「这个寄存器有位域宏吗」，多收无害。
            regs.add(reg)

    widths: dict[str, int] = {}
    for m in _MSK.finditer(text):
        widths[m.group(1)] = bin(int(m.group(2), 0)).count("1")
    return exact, norm, regs, widths


def parse_device_header(path: Path | str) -> DeviceHeader:
    """解析 CMSIS 器件头。"""
    t0 = time.time()
    path = Path(path)
    raw = path.read_text(encoding="utf-8", errors="replace")
    text = _CONT.sub(" ", raw)

    macros: dict[str, str] = {}
    for m in _PLAIN_MACRO.finditer(text):
        macros.setdefault(m.group(1), m.group(2).strip())

    instances: dict[str, Instance] = {}
    for m in _INSTANCE.finditer(text):
        instances[m.group(1)] = Instance(name=m.group(1), struct=m.group(2),
                                         base_macro=m.group(3))

    structs, conditional = _parse_structs(raw)
    field_pos, field_pos_norm, regs_with_pos, widths = _parse_field_pos(text)
    header = DeviceHeader(
        path=path.name,
        macros=macros,
        instances=instances,
        structs=structs,
        field_pos=field_pos,
        field_pos_norm=field_pos_norm,
        regs_with_pos_macros=regs_with_pos,
        field_width=widths,
        structs_with_conditionals=conditional,
        parse_ms=round((time.time() - t0) * 1000, 1),
    )
    return header


def default_header_name(mcu: str = "stm32h743zit6") -> str:
    """本芯片对应的器件头文件名。

    `stm32h743xx.h` 覆盖整条 H743 料号（`x` 是封装/温度/Flash 代码的占位），
    所以从 `stm32h743zit6` 里取不到它 —— 直接由 MCU 家族名派生。
    """
    family = mcu.lower()[:9]          # stm32h743
    return f"{family}xx.h"


# --------------------------------------------------------------------------
# 命名口径：SVD 外设名 ↔ 器件头实例名
# --------------------------------------------------------------------------
# SVD 与器件头对同一外设的命名约定不同，这不是错误，是**两种渲染口径**。
# 处理方式与 AVR 侧的 `SREG_C` 一致：先按规则自动匹配，剩下的显式登记，
# **不静默跳过**（跳过了就等于把"没比过"混进"比过了都对"）。

#: 自动规则兜不住的别名。键 = SVD 外设名，值 = 器件头实例名。
HEADER_ALIASES: dict[str, str] = {
    # USB OTG：SVD 拆成 GLOBAL/HOST/DEVICE/PWRCLK 四个外设共用一条基址，
    # 器件头是一个 `USB1_OTG_HS` / `USB2_OTG_FS` 实例。
    "OTG1_HS_GLOBAL": "USB1_OTG_HS",
    "OTG1_HS_HOST": "USB1_OTG_HS",
    "OTG1_HS_DEVICE": "USB1_OTG_HS",
    "OTG1_HS_PWRCLK": "USB1_OTG_HS",
    "OTG2_HS_GLOBAL": "USB2_OTG_FS",
    "OTG2_HS_HOST": "USB2_OTG_FS",
    "OTG2_HS_DEVICE": "USB2_OTG_FS",
    "OTG2_HS_PWRCLK": "USB2_OTG_FS",
    # 以太网：SVD 拆成 MAC/MTL/DMA 三段，器件头只有 `ETH`。
    "Ethernet_MAC": "ETH",
    "Ethernet_MTL": "ETH",
    "Ethernet_DMA": "ETH",
    # 延时块：SVD 叫 DELAY_Block_*，器件头叫 DLYB_*。
    "DELAY_Block_SDMMC1": "DLYB_SDMMC1",
    "DELAY_Block_SDMMC2": "DLYB_SDMMC2",
    "DELAY_Block_QUADSPI": "DLYB_QUADSPI",
    # 高分辨率定时器：SVD 不带给实例编号的 `HRTIM_`，器件头是 `HRTIM1_`。
    # （`HRTIM_TIMA..E` 能靠插编号规则自动配上，Master/Common 不能。）
    "HRTIM_Master": "HRTIM1",
    "HRTIM_Common": "HRTIM1_COMMON",
    # 大小写差异。
    "Flash": "FLASH",
    "ADC3_Common": "ADC3_COMMON",
    "ADC12_Common": "ADC12_COMMON",
    # 器件头里没有独立实例指针（只有 `_BASE` 宏或直接地址宏）。
    "FMC": "FMC_Bank1_R",
}

#: SVD 的外设里**不属于器件头管辖**的部分 —— 由 `core_cm7.h` 或编译器
#: 内建描述，拿器件头去比对它们没有意义。逐条写理由，不做成"静默白名单"。
CORE_PERIPHERALS: dict[str, str] = {
    "NVIC": "Cortex-M7 内核外设，CMSIS 在 core_cm7.h 里描述",
    "NVIC_STIR": "同上（NVIC 的 STIR 别名）",
    "MPU": "Cortex-M7 内核外设",
    "SCB": "Cortex-M7 系统控制块",
    "SCB_ACTRL": "同上（辅助控制寄存器视图）",
    "STK": "Cortex-M7 系统节拍定时器",
    "FPU": "Cortex-M7 浮点单元",
    "FPU_CPACR": "同上（CPACR 寄存器视图）",
    "PF": "Cortex-M7 预取单元寄存器",
    "AXI": "Cortex-M7 AXI 接口寄存器",
}

#: 器件片内外设，但器件头**没有给出实例指针/结构体** —— 只能跳过。
#: 与 CORE_PERIPHERALS 分开，因为它们不是内核外设，理由不同。
NO_HEADER_INSTANCE: dict[str, str] = {
    "AC": "器件头只有 `AC_BASE` 与直接地址宏，无实例指针/结构体",
    "CAN_CCU": "同上",
    "DFSDM": "SVD 给成单个外设（基址 0x40017000），器件头拆成 "
             "DFSDM1_Channel*/DFSDM1_Filter* 两组实例，无法一对一",
}

#: 宏前缀别名 —— 器件头把某些外设的位域宏挂在**别的名字**下。
#: 键 = 外设/组名（含去编号形式），值 = 额外的可接受前缀。
PREFIX_ALIASES: dict[str, tuple[str, ...]] = {
    # H743 器件头没有任何 `LPUART_*` 宏（实测 grep 计数 0），
    # LPUART1/2 与 USART 共用 `USART_TypeDef` 和 `USART_*` 宏。
    "LPUART": ("USART",),
    "LPUART1": ("USART",),
    "LPUART2": ("USART",),
}

#: 器件头里「有实例但结构体不含寄存器成员」的外设（只能比基址）。
#: 判断的理由：MDMA 在器件头里根本没有 `MDMA_TypeDef`（寄存器靠直接地址宏
#: 访问），此时"结构体里找不到成员"**不是**SVD 错。
NO_STRUCT_REGISTERS: dict[str, str] = {
    "MDMA": "器件头未建模 MDMA_TypeDef，寄存器以直接地址宏给出",
}


def _insert_family_digit(name: str) -> str:
    """`IWDG` → `IWDG1`、`HRTIM_TIMA` → `HRTIM1_TIMA`。

    SVD 给外设编号以 1 为基（`OTG1_HS_*`、`DFSDM1_*`），器件头对只有一个
    实例的外设不带编号（`IWDG`、`WWDG`、`DAC`、`SWPMI`、`HRTIM`）。
    """
    return re.sub(r"^([A-Z]+)", r"\g<1>1", name, count=1)


def map_peripheral(header: DeviceHeader, svd_name: str) -> tuple[str | None, str]:
    """SVD 外设名 → 器件头实例名。

    返回 ``(实例名或 None, 匹配方式)``。匹配方式取值：

    ``exact`` / ``case`` / ``alias`` / ``digit`` —— 成功路径；
    ``core`` —— 内核外设，不在器件头管辖（CORE_PERIPHERALS）；
    ``no_instance`` —— 器件头没有实例指针/结构体（NO_HEADER_INSTANCE）；
    ``unmapped`` —— 器件头无对应实例（**必须在报告里逐条列出**，不静默丢）。
    """
    if svd_name in header.instances:
        return svd_name, "exact"
    if svd_name in HEADER_ALIASES and HEADER_ALIASES[svd_name] in header.instances:
        return HEADER_ALIASES[svd_name], "alias"

    upper = svd_name.upper()
    for name in header.instances:
        if name.upper() == upper:
            return name, "case"

    digit = _insert_family_digit(svd_name)
    if digit in header.instances:
        return digit, "digit"
    if svd_name in CORE_PERIPHERALS:
        return None, "core"
    if svd_name in NO_HEADER_INSTANCE:
        return None, "no_instance"
    return None, "unmapped"


def register_name_variants(reg: str, peripheral: str, group: str) -> list[str]:
    """SVD 寄存器名的可能拼法。

    SVD 对部分外设把前缀写进寄存器名（`FDCAN_CREL` / `FDCAN_CCCR`），
    器件头的结构体成员是裸名（`CREL` / `CCCR`）。剥前缀后比。
    返回列表，**首个永远是原名**，调用方按序试。
    """
    out = [reg]
    for pfx in (peripheral, group):
        if pfx and reg.startswith(pfx + "_"):
            out.append(reg[len(pfx) + 1:])
    return out
