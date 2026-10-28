"""Source Code Reviewer -- fast pre-build structural scan.

Scans source code for register names and bit-field references, cross-references
with the chip knowledge base, and returns structured diagnostics for Agent feedback.

Usage:
    from firmforge.core.source_reviewer import SourceReviewer, SourceReviewResult

    validator = SourceReviewer(knowledge_base)
    result = validator.validate(source_code)

    if not result.passed:
        for v in result.violations:
            print(f"  ERROR line {v.line}: {v.register} - {v.reason}")
        # Block compilation, feed errors back to AI for fix
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from firmforge.knowledge.device_truth import DeviceTruth, Verdict
from firmforge.knowledge.knowledge_base import KnowledgeBase

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Detection strategy:
#
# 1. Register assignment context: identifiers that appear as lvalues before
#    assignment operators (=, |=, &=, etc.) are treated as register names.
#    This catches PORTB, UCSR0A, UBRR0L, and also hallucinated ones like
#    PORTZ, UCSR9A, DDRQ.
#
# 2. Bit-field shift context: identifiers inside (1 << NAME) or _BV(NAME)
#    are treated as bit-field names. This catches TXEN0, RXEN0, PORTB7, etc.
#
# 3. Broader register scan: identifiers that look like AVR register names
#    (ALL_CAPS, 3+ chars, not in known-safe list) appearing in any context
#    are also checked. This catches reads like `if (UCSR0A & (1 << UDRE0))`.
# ---------------------------------------------------------------------------

# Assignment operators that indicate register write context
_ASSIGN_OPS = r'(?:\|=|&=|<<=|>>=|^=|\+=|-=|\*=|/=|%=|=)'

# Pattern 1: Register in assignment context:  IDENTIFIER op= value
# Matches: PORTB = 0xFF, UCSR0B |= (1<<RXEN0), DDRB &= ~(1<<7)
# The identifier must be ALL_CAPS (register naming convention)
#
# 前置断言 `(?<![.>])` 排除**成员访问**：`osc.PLL.PLLM = BSP_PLL_M;` 里的
# `PLLM` 是 HAL 结构体成员，不是寄存器。少了这个断言，`\b` 会在 `.` 与 `P`
# 之间成立，把裸名 `PLLM` 抓进赋值上下文 —— 实测在 bsp_init.c 上误报 8 条
# （PLLM/PLLN/PLLP/PLLQ/PLLR/PLLRGE/PLLVCOSEL/PLLFRACN，全部是
# `RCC_OscInitTypeDef::PLL` 的成员），把「寄存器审查」计数污染成 2/10，
# 让人误以为有 8 个寄存器没解析出来。
# `PERIPH->REG` / `PERIPH.REG` 由 Pattern 4 用限定名单独负责，不会漏。
_REGISTER_ASSIGN_RE = re.compile(
    r'(?<![.>])\b([A-Z][A-Z0-9_]{2,})\s*' + _ASSIGN_OPS
)

# Pattern 2: Bit-field in shift/macro context:  (1 << NAME) or _BV(NAME)
_FIELD_REF_RE = re.compile(
    r'(?:'
    r'\(\s*1\s*<<\s*([A-Z][A-Z0-9_]*)\s*\)'  # (1 << FIELD)
    r'|_BV\s*\(\s*([A-Z][A-Z0-9_]*)\s*\)'     # _BV(FIELD)
    r'|BIT\s*\(\s*([A-Z][A-Z0-9_]*)\s*\)'     # BIT(FIELD)
    r')'
)

# Pattern 3: Broader register read context: identifier & something, or something & identifier
# Matches: UCSR0A &, (UCSR0A), if (UCSR0A
# We use a simpler approach: find ALL_CAPS identifiers of 3+ chars that aren't
# in the known-safe list, then check each against the reference library.
_ALL_CAPS_IDENT_RE = re.compile(r'\b([A-Z][A-Z0-9_]{2,})\b')

# Pattern 4: STM32 外设寄存器访问 —— PERIPH->REG 或 PERIPH.REG。
# 命中后必须用**限定名**查：STM32 的 CR1 / SR / DR 跨外设重名，用裸名查会
# 解析到别的外设，且不报错。
#
# 实例名曾写成 `[A-Z][A-Z0-9]{1,15}`，只认全大写。CMSIS 的十个内核组里有
# 两个是驼峰 —— `SysTick` 与 `CoreDebug` —— 于是 `SysTick->LOAD`、
# `CoreDebug->DHCSR` **一个字都匹配不上**，连 warning 都没有：知识库明明有
# （SysTick.LOAD = 0xE000E014，CoreDebug.DHCSR = 0xE000EDF0），审查却完全
# 空转。用 SysTick 做时基的裸机项目，S2 这一段等于不存在。`DMA1_Stream0->CR`
# 这种带下划线的实例名同样漏。所以实例名放宽到标识符全集。
#
# 放宽的代价是会把结构体成员链也抓进来（`osc.PLL.PLLM`、`huart1.Instance`）。
# 用两个约束挡住：
#   ① 点号形式只认**全大写**实例名 —— 小写 + `.` 几乎必然是结构体；
#   ② 箭头形式仍走「寄存器在库里有主才算可疑」的三条件（见下方 Phase 0）。
_PERIPH_ACCESS_RE = re.compile(
    r'\b([A-Za-z_][A-Za-z0-9_]{1,24})\s*(->|\.)\s*([A-Z][A-Z0-9_]{1,24})\b'
)

# Pattern 5: STM32 CMSIS 位宏 —— 至少含一个下划线，且整体全大写。
# USART_CR1_TE / GPIO_MODER_MODER0 命中；HAL_GPIO_WritePin（有大小写）
# 与 __HAL_RCC_XXX（前导下划线）不命中。
_FIELD_MACRO_RE = re.compile(r'\b([A-Z][A-Z0-9]*_[A-Z0-9_]+)\b')

# Known AVR-safe identifiers that are NOT register names
_KNOWN_NON_REGISTERS = {
    # Arduino constants
    "HIGH", "LOW", "INPUT", "OUTPUT", "INPUT_PULLUP",
    "LED_BUILTIN",
    # Analog pin aliases
    "A0", "A1", "A2", "A3", "A4", "A5",
    "A6", "A7", "A8", "A9", "A10", "A11", "A12", "A13", "A14", "A15",
    # Arduino objects
    "Serial", "Serial1", "Serial2", "Serial3",
    "SPI", "Wire", "EEPROM",
    # C types and keywords
    "uint8_t", "uint16_t", "uint32_t", "int8_t", "int16_t", "int32_t",
    "size_t", "void", "NULL", "sizeof", "true", "false",
    # Macros / constants
    "F_CPU", "UART", "USART", "DEC", "BIN", "OCT", "HEX",
    "PI", "HALF_PI", "TWO_PI", "DEG_TO_RAD", "RAD_TO_DEG",
    "LSBFIRST", "MSBFIRST",
    "CHANGE", "FALLING", "RISING",
    "DEFAULT", "INTERNAL", "INTERNAL1V1", "INTERNAL2V56", "EXTERNAL",
    "SERIAL", "DISPLAY", "KEYBOARD", "MOUSE", "FIRMATA",
    # Common AVR macro names (not registers)
    "_BV", "BIT", "SET_BIT", "CLEAR_BIT", "TOGGLE_BIT",
    "ISR", "SIGNAL", "INTERRUPT", "EMPTY_INTERRUPT",
    "sei", "cli", "interrupts", "noInterrupts",
    "sleep_mode", "idle_mode", "adc_power_off",
    # Compiler / preprocessor
    "PRAGMA", "DEFINE", "INCLUDE", "IFDEF", "IFNDEF", "ENDIF",
    "UNDEFINED", "ERROR", "WARNING",
}

# Known AVR register name prefixes (for hallucination heuristic)
# If an identifier starts with one of these but isn't in the reference library,
# it's likely a hallucinated register (higher confidence error)
_REG_PREFIXES = (
    "PORT", "DDR", "PIN",
    "UCSR", "UDR", "UBRR",
    "TCCR", "TCNT", "OCR", "ICR", "TIFR", "TIMSK", "ETIFR", "ETIMSK",
    "ADMUX", "ADC", "ADATE", "ADIF", "ADIE", "ADEN", "ADSC", "ADPS",
    "EECR", "EEDR", "EEAR", "EERE", "EEMWE", "EEWE",
    "SPCR", "SPSR", "SPDR", "SPI",
    "TWCR", "TWSR", "TWBR", "TWDR", "TWAR", "TWAMR", "TWINT",
    "CLKPR", "CLKPS", "CLKPCE", "SMCR", "MCUCR", "MCUSR",
    "WDTCSR", "WDE", "WDCE", "WDP", "WDIF", "WDIE",
    "EICRA", "EICRB", "EIMSK", "EIFR",
    "PCICR", "PCIFR", "PCMSK", "PCIE", "PCIF",
    "OSCCAL", "PRR",
    "ASSR", "EXCLK",
    "GPIOR", "GTCCR",
    "SPMCR", "SPMCSR",
    "RAMPZ", "EIND",
)


@dataclass
class _ScanState:
    """一次 validate() 扫描的跨行状态（去重集合 + 外设实例名索引）。"""

    # 已查过的 (寄存器, 行号) / (位名, 行号) —— 同名同行只报一次
    seen_registers: set[tuple[str, int]] = field(default_factory=set)
    seen_fields: set[tuple[str, int]] = field(default_factory=set)
    # 未知外设名的提示按 (外设, 寄存器) 全局去重 —— 同一个 `GPIOZ->BSRR`
    # 在文件里出现 5 次，报 1 条就够。
    seen_unknown_periph: set[tuple[str, str]] = field(default_factory=set)
    # 已知外设实例名（USART1 / GPIOA / DMA1）；空集 = 该芯片知识库无外设分组
    peripherals: set[str] = field(default_factory=set)


@dataclass
class SourceReviewViolation:
    """A single source review violation or warning.

    Attributes:
        register: Register or field name found in code.
        field: Field name if applicable (empty for register-level).
        file: Source file the reference came from (基名或相对路径)。
            跨文件聚合时这是定位的唯一线索，缺了等于只能靠数数。
        line: 1-based line number in source code.
        line_text: The actual source line text.
        severity: "error" (blocks compilation) or "warning" (informational).
        reason: Human-readable explanation of the violation.
        suggestion: How to fix the issue.
        kb_gap: True = 器件头确认芯片上有、但知识库未收录。这类**不是**错，
            是工具的收录缺口 —— 与"幻觉"在知识库里长得一样，必须分开报。
        evidence: 判据来源（``器件头 TIM_TypeDef.RCR`` / 空）。空串表示本机
            没有器件头，**未做交叉验证**，不下对错结论。
        allowed_reason: 命中项目豁免表时填理由；非空表示不计入惩罚。
    """

    register: str
    field: str = ""
    file: str = ""
    line: int = 0
    line_text: str = ""
    severity: str = "error"
    reason: str = ""
    suggestion: str = ""
    kb_gap: bool = False
    evidence: str = ""
    allowed_reason: str = ""

    def __str__(self) -> str:
        loc = f"{self.file}:{self.line}" if self.file and self.line \
            else (f"line {self.line}" if self.line else "unknown line")
        target = f"{self.register}.{self.field}" if self.field else self.register
        tag = f"[{self.severity.upper()}]"
        if self.allowed_reason:
            tag = "[ALLOWED]"
        elif self.kb_gap:
            tag = "[KB-GAP]"
        tail = f"{self.reason}（{self.evidence}）" if self.evidence else self.reason
        if self.allowed_reason:
            tail += f" —— 已由项目声明豁免：{self.allowed_reason}"
        return f"{tag} {loc}: {target} -- {tail}"


@dataclass
class SourceReviewResult:
    """Result of source code review validation.

    Attributes:
        passed: True if no errors (warnings are OK).
        violations: List of error-level violations (blocks compilation).
        warnings: List of warning-level issues (informational).
        registers_checked: Total register references found in code.
        registers_resolved: How many were found in reference library.
        fields_checked: Total bit-field references found.
        fields_resolved: How many fields were resolved.
        allowed: 命中项目豁免表的条目（不计惩罚，但仍然列出来）。
        kb_gaps: 器件头确认存在、知识库未收录的条目数 —— 这是工具的缺口，
            **不是**源码的错。与 ``len(violations)`` 分开计，否则"知识库不全"
            会被读成"代码有问题"。
        cross_checked: 本次是否做了器件头交叉验证（无器件头时为 False）。
    """

    passed: bool = True
    violations: list[SourceReviewViolation] = field(default_factory=list)
    warnings: list[SourceReviewViolation] = field(default_factory=list)
    registers_checked: int = 0
    registers_resolved: int = 0
    fields_checked: int = 0
    fields_resolved: int = 0
    allowed: list[SourceReviewViolation] = field(default_factory=list)
    kb_gaps: int = 0
    cross_checked: bool = False
    #: 被项目声明豁免的寄存器条数。这些既不算缺口也不算错 —— 从置信度分母
    #: 里剔出去，否则"豁免"只是不阻断、分数照样被打死，等于没豁免。
    registers_allowed: int = 0

    def summary(self) -> str:
        """Human-readable summary string."""
        lines = [
            f"Code Review: {'PASS' if self.passed else 'FAIL'}",
            f"  Registers: {self.registers_resolved}/{self.registers_checked} resolved",
            f"  Fields: {self.fields_resolved}/{self.fields_checked} resolved",
            f"  Errors: {len(self.violations)}",
            f"  Warnings: {len(self.warnings)}",
        ]
        if self.kb_gaps:
            lines.append(f"  KB gaps (芯片有、库未收录): {self.kb_gaps}")
        if self.allowed:
            lines.append(f"  Allowed by project: {len(self.allowed)}")
        for v in self.violations:
            lines.append(f"  {v}")
        for w in self.warnings:
            lines.append(f"  {w}")
        for a in self.allowed:
            lines.append(f"  {a}")
        return "\n".join(lines)


class SourceReviewer:
    """Source code reviewer — fast pre-build structural scan.

    Implements 规划 §2.7 引用门禁 Code Review:
    - Generated register/bitfield values must carry $ref to knowledge base
    - Unresolvable references are blocked before compilation
    - Prevents "hallucinated register" and "wrong clock tree" errors

    Args:
        knowledge_base: KnowledgeBase instance with reference library loaded.
        device_truth: 器件头查询层（``DeviceTruth``）。给了才能在「知识库查
            不到」时区分「未收录」与「幻觉」；不给则一律按 warning 处理，
            **不下 error 结论** —— 没有第二份证据就没有资格说源码写错了。
        allowlist: 项目级豁免表（``ReviewAllowlist``）。命中的条目不计惩罚，
            但仍原样列出。
    """

    def __init__(self, knowledge_base: KnowledgeBase,
                 device_truth: DeviceTruth | None = None,
                 allowlist: Any = None) -> None:
        self._knowledge_base = knowledge_base
        self._device_truth = device_truth
        self._allowlist = allowlist

    @staticmethod
    def _strip_comments(source: str) -> str:
        """Remove all comments from source code, preserving line count.

        Strategy: process line by line for // comments, then
        line-range aware for /* */ blocks.
        """
        lines = source.split('\n')
        result: list[str] = []
        in_block = False
        for line in lines:
            if in_block:
                # Inside /* */ only check for closing
                end = line.find('*/')
                if end != -1:
                    in_block = False
                    result.append('')
                else:
                    result.append('')
                continue

            # Outside block: check for /* that starts a new block
            start = line.find('/*')
            slash = line.find('//')
            if start != -1 and (slash == -1 or start < slash):
                # /* comment: remove from start
                end = line.find('*/', start + 2)
                if end != -1:
                    # Single-line block: /* xxx */ → keep rest after */
                    result.append(line[:start] + ' ' + line[end + 2:])
                else:
                    # Multi-line block start
                    in_block = True
                    result.append(line[:start])
            elif slash != -1:
                # // comment: remove from slash
                result.append(line[:slash])
            else:
                result.append(line)
        return '\n'.join(result)

    @property
    def knowledge_base(self) -> KnowledgeBase:
        return self._knowledge_base

    @property
    def device_truth(self) -> DeviceTruth | None:
        """器件头查询层。None = 未注入，此时不做交叉验证。"""
        return self._device_truth

    @classmethod
    def for_board(cls, knowledge_base: KnowledgeBase,
                  paradigm: str = "arduino", chip: str | None = None,
                  board: dict[str, Any] | None = None,
                  allowlist: Any = None) -> SourceReviewer:
        """Create a validator pre-loaded with the correct register library.

        Routes by ``board`` (preferred) or ``paradigm``:

          board.yaml platform: arduino → reference/avr/<chip>/registers.json
          board.yaml platform: stm32   → cache/knowledge/stm32/<系列>/<chip>/registers.json
          paradigm hal                 → stm32（同 platform: stm32）
          paradigm stc / esp_idf       → stc / esp32

        映射表收在 ``firmforge.knowledge.platforms`` —— 之前写死在这里的
        局部 dict 缺 ``hal``，导致 STM32 芯片被拿到 AVR 目录下找。
        """
        from firmforge.knowledge.platforms import device_series, library_platform

        platform = library_platform(board, paradigm)
        if chip is None and board:
            chip = (board.get("mcu") or {}).get("chip")
        knowledge_base.load_reference(platform, chip=chip,
                                      series=device_series(board, chip))
        # 器件头只在有 CMSIS 的设备上存在（STM32）。AVR 侧返回不可用的实例，
        # 三态判定退化为「不知道」，AVR 原有的前缀启发式照旧。
        return cls(knowledge_base, device_truth=DeviceTruth.load(chip),
                   allowlist=allowlist)

    def validate(self, source_code: str,
                 filename: str = "<generated>") -> SourceReviewResult:
        """Review source code for structural issues before compilation.

        Scans for:
        1. Register names in assignment context (lvalue before =, |=, &=, etc.)
        2. Bit-field names in shift expressions ((1 << NAME), _BV(NAME))
        3. Broader ALL_CAPS identifiers that look like register names

        Each found reference is checked against the reference library.
        Unresolved references with known register prefixes are errors;
        other unresolved identifiers are warnings.

        Args:
            source_code: C/C++ source code to validate.
            filename: Source filename for error reporting.

        Returns:
            SourceReviewResult with violations, warnings, and statistics.
        """
        # Strip ALL comment content before scanning.
        # - // line comments (including trailing)
        # - /* */ block comments (multi-line, non-greedy)
        # This prevents false positives from comment text (e.g. "GND", "SIG"
        # in documentation blocks) and trailing inline comments.
        # After stripping, replaced content is blank lines to preserve
        # line numbering for error reporting.
        source_code = self._strip_comments(source_code)

        result = SourceReviewResult()
        # 有没有第二份证据（器件头）。没有时本文件所有的"未解析"都只能
        # 报 warning —— 不知道就说不知道，不能拿知识库的缺口当源码的错。
        result.cross_checked = bool(
            self._device_truth is not None and self._device_truth.available)
        lines = source_code.splitlines()

        # 已知外设实例名（USART1 / GPIOA / DMA1）。空集说明当前芯片的知识库
        # 没有外设分组（AVR 也有分组，但 AVR 代码不写 PERIPH->REG），此时
        # Phase 0 整体跳过，不为没有的东西付扫描成本。
        state = _ScanState(
            peripherals=self._knowledge_base.peripheral_names())

        for line_num, line in enumerate(lines, start=1):
            stripped = self._strip_strings(line).strip()

            # Skip comments, preprocessor, and empty lines
            if not stripped:
                continue
            if stripped.startswith(("//", "#", "/*", "*")):
                continue

            # 每个阶段是独立方法，共享 state（跨行去重）与 result。
            # 阶段间有两份行内集合要传递：限定名寄存器（Phase 0 → 1b/2 的
            # 去重依据）与位名（Phase 1 → 1b/2/3 的去重依据）。
            peripheral_regs = self._scan_peripheral_access(
                result, stripped, line_num, state)
            field_names = self._scan_bit_fields(result, stripped, line_num, state)
            self._scan_cmsis_macros(result, stripped, line_num, state,
                                     peripheral_regs, field_names)
            self._scan_assignment_registers(result, stripped, line_num, state,
                                            field_names, peripheral_regs)
            self._scan_broad_registers(result, stripped, line, line_num, state,
                                       field_names)

        # 文件名必须在**每一条**违规上落地。跨文件聚合后如果只有计数、没有
        # 文件名，读日志的人只能自己 import 本模块逐个文件跑一遍才能定位
        # —— 这件事真实发生过（2026-10-27，用户用脚本逐个 validate_file 才
        # 找到 blackbox.c:161）。文件名是诊断的一部分，不是装饰。
        # 顺序不能反：豁免规则可以限定到具体文件，匹配前必须先有文件名。
        for item in (*result.violations, *result.warnings):
            if not item.file:
                item.file = filename

        self._apply_allowlist(result)
        self._log_verdict(result)

        return result

    # ------------------------------------------------------------------
    # 逐行扫描阶段（validate 的五个 Phase，共享 _ScanState）
    # ------------------------------------------------------------------

    def _scan_peripheral_access(self, result: SourceReviewResult,
                                stripped: str, line_num: int,
                                state: "_ScanState") -> set[str]:
        """Phase 0: 外设寄存器访问 PERIPH->REG / PERIPH.REG。

        STM32 的写法。此前这类引用完全没被识别：`USART1->CR1` 里的裸名
        `CR1` 会落到 Phase 2，而裸名在 STM32 上跨 36 个外设重名，
        lookup_register("CR1") 返回其中随便一个 —— 审查显示「已解析」，
        实际解析到了别的外设。限定名查不到才是真错。

        返回本行以限定名出现过的寄存器名集合（Phase 1b/2 的去重依据）。
        """
        peripheral_regs_on_line: set[str] = set()
        if not state.peripherals:
            return peripheral_regs_on_line

        for match in _PERIPH_ACCESS_RE.finditer(stripped):
            periph = match.group(1).upper()
            op = match.group(2)
            reg = match.group(3).upper()

            # **首字母必须大写**才是实例名。CMSIS 的实例一律大写开头
            # （GPIOA / USART1 / DMA1_Stream0 / SysTick / CoreDebug），
            # 而结构体成员与变量都小写：`p->port->BSRR`、`osc.PLL.PLLM`、
            # `huart1->Instance`。这条判据比"点号 vs 箭头"更准 ——
            # 箭头形式下同样会出现成员指针链（`p->port->BSRR` 就曾被
            # 当成外设 PORT，报了一条 `PORT.BSRR` 的假 warning）。
            if not match.group(1)[0].isupper():
                continue

            if periph not in state.peripherals:
                self._note_unknown_peripheral(
                    result, periph, reg, op, stripped, line_num,
                    state.seen_unknown_periph)
                continue
            peripheral_regs_on_line.add(reg)

            key = (f"{periph}.{reg}", line_num)
            if key in state.seen_registers:
                continue
            state.seen_registers.add(key)
            result.registers_checked += 1

            if self._knowledge_base.lookup_register_qualified(periph, reg):
                result.registers_resolved += 1
            else:
                self._record_unresolved(result, periph, reg, stripped,
                                        line_num)
        return peripheral_regs_on_line

    def _scan_bit_fields(self, result: SourceReviewResult,
                         stripped: str, line_num: int,
                         state: "_ScanState") -> set[str]:
        """Phase 1: 位域引用 (1 << X) / _BV(X)。

        先于寄存器扫描提取，是为了把位名从后续寄存器扫描中排除。
        返回本行出现的位名集合（Phase 1b/2/3 的去重依据）。
        """
        field_names_on_line: set[str] = set()
        for match in _FIELD_REF_RE.finditer(stripped):
            field_name = match.group(1) or match.group(2) or match.group(3)
            if not field_name:
                continue
            field_name = field_name.upper()
            field_names_on_line.add(field_name)

            # Skip known safe constants
            if field_name in _KNOWN_NON_REGISTERS:
                continue

            key = (field_name, line_num)
            if key in state.seen_fields:
                continue
            state.seen_fields.add(key)

            result.fields_checked += 1

            # Try to resolve the field
            if self._resolve_field(field_name):
                result.fields_resolved += 1
            else:
                result.warnings.append(SourceReviewViolation(
                    register=field_name,
                    line=line_num,
                    line_text=stripped,
                    severity="warning",
                    reason=f"Bit-field '{field_name}' not found in reference "
                           f"library (may be a macro or constant)",
                    suggestion=f"Verify that '{field_name}' is defined in the "
                               f"Arduino core or AVR headers",
                ))
        return field_names_on_line

    def _scan_cmsis_macros(self, result: SourceReviewResult,
                           stripped: str, line_num: int,
                           state: "_ScanState", peripheral_regs: set[str],
                           field_names: set[str]) -> None:
        """Phase 1b: STM32 CMSIS 位宏（USART_CR1_TE）。

        AVR 的位名被 (1 << X) / _BV(X) 包着，Phase 1 能认出来；STM32
        直接写宏名，外面没有移位。判据分三档：
          命中全名索引 → 真位
          前缀命中     → 该前缀下确有一批真位，说明寄存器选对了、位名写错了
          都不命中     → HAL 常量（GPIO_PIN_7）或别的库的宏，放过
        """
        if not state.peripherals:
            return

        for match in _FIELD_MACRO_RE.finditer(stripped):
            macro = match.group(1).upper()
            if macro in peripheral_regs:
                continue          # Phase 0 已按限定名查过
            if macro in _KNOWN_NON_REGISTERS:
                continue
            if macro in field_names:
                continue          # Phase 1 已按 (1 << X) 形态处理

            if self._knowledge_base.lookup_field(macro):
                key = (macro, line_num)
                if key in state.seen_fields:
                    continue
                state.seen_fields.add(key)
                result.fields_checked += 1
                result.fields_resolved += 1
                continue

            prefix = self._knowledge_base.field_prefix_of(macro)
            if not prefix:
                continue          # HAL 常量，不在寄存器库里是正常的

            key = (macro, line_num)
            if key in state.seen_fields:
                continue
            state.seen_fields.add(key)
            result.fields_checked += 1
            result.violations.append(SourceReviewViolation(
                register=macro,
                line=line_num,
                line_text=stripped,
                severity="error",
                reason=(f"Bit-field macro '{macro}' not found; prefix "
                        f"'{prefix}' has known fields in reference"),
                suggestion=(f"'{prefix}' 下有已知位宏 —— 寄存器选对了、"
                            f"位名写错了。用 'ff context <board> "
                            f"--topic <外设>' 核对位名。"),
            ))
            result.passed = False

    def _scan_assignment_registers(self, result: SourceReviewResult,
                                   stripped: str, line_num: int,
                                   state: "_ScanState", field_names: set[str],
                                   peripheral_regs: set[str]) -> None:
        """Phase 2: 赋值语境下的寄存器名（PORTB = ...）。"""
        for match in _REGISTER_ASSIGN_RE.finditer(stripped):
            reg_name = match.group(1)

            # Skip known non-register identifiers
            if reg_name in _KNOWN_NON_REGISTERS:
                continue

            # Skip user-defined names (contain underscore — AVR registers never do)
            if "_" in reg_name:
                continue

            # Skip if this is actually a field name on this line
            if reg_name.upper() in field_names:
                continue

            # Skip registers already resolved as PERIPH->REG on this line:
            # 裸名在 STM32 上跨外设重名，再查一遍只会得到假通过
            if reg_name.upper() in peripheral_regs:
                continue

            # Skip common C keywords/types that might match
            if reg_name.lower() in ("return", "while", "break", "continue"):
                continue

            key = (reg_name, line_num)
            if key in state.seen_registers:
                continue
            state.seen_registers.add(key)

            result.registers_checked += 1

            # Look up in reference library
            reg_entry = self._knowledge_base.lookup_register(reg_name)
            if reg_entry:
                result.registers_resolved += 1
            else:
                # Check if it starts with a known register prefix
                is_likely_register = reg_name.upper().startswith(_REG_PREFIXES)

                if is_likely_register:
                    result.violations.append(SourceReviewViolation(
                        register=reg_name,
                        line=line_num,
                        line_text=stripped,
                        severity="error",
                        reason=f"Register '{reg_name}' not found in reference "
                               f"library (hallucinated register with known prefix)",
                        suggestion="Verify register name against ATmega2560 "
                                   "datasheet. Use a known register or add it "
                                   "to knowledge/reference/avr/registers.json",
                    ))
                    result.passed = False
                else:
                    result.warnings.append(SourceReviewViolation(
                        register=reg_name,
                        line=line_num,
                        line_text=stripped,
                        severity="warning",
                        reason=f"Identifier '{reg_name}' in assignment context "
                               f"not found in reference library",
                        suggestion="If this is a register, verify its name. "
                                   "Otherwise this may be a variable name.",
                    ))

    def _scan_broad_registers(self, result: SourceReviewResult,
                              stripped: str, line: str, line_num: int,
                              state: "_ScanState", field_names: set[str]) -> None:
        """Phase 3: 更宽的全大写标识符扫描（寄存器读取，非赋值）。

        如 if (UCSR0A & (1 << UDRE0)) / val = PINB。
        先剥字符串字面量，避免匹配到字符串里的寄存器样名字。
        """
        scan_line = self._strip_strings(line)

        for match in _ALL_CAPS_IDENT_RE.finditer(scan_line):
            ident = match.group(1)

            # Skip known safe identifiers
            if ident in _KNOWN_NON_REGISTERS:
                continue

            # Skip user-defined names (contain underscore — AVR registers never do)
            if "_" in ident:
                continue

            # Skip if already checked as assignment register or field
            if (ident, line_num) in state.seen_registers:
                continue
            if ident.upper() in field_names:
                continue

            # Skip if not register-like (must start with a known prefix)
            if not ident.upper().startswith(_REG_PREFIXES):
                continue

            # Skip common false positives
            if ident in ("ISR", "SIGNAL", "DEFINE", "INCLUDE", "PRAGMA",
                         "F_CPU", "LED_BUILTIN"):
                continue

            key = (ident, line_num)
            if key in state.seen_registers:
                continue
            state.seen_registers.add(key)

            result.registers_checked += 1

            reg_entry = self._knowledge_base.lookup_register(ident)
            if reg_entry:
                result.registers_resolved += 1
            else:
                result.violations.append(SourceReviewViolation(
                    register=ident,
                    line=line_num,
                    line_text=stripped,
                    severity="error",
                    reason=f"Register '{ident}' not found in reference library "
                           f"(hallucinated register with known prefix)",
                    suggestion="Verify register name against ATmega2560 "
                               "datasheet.",
                ))
                result.passed = False

    # ------------------------------------------------------------------
    # 豁免与日志
    # ------------------------------------------------------------------
    def _apply_allowlist(self, result: SourceReviewResult) -> None:
        """把命中项目豁免表的条目从"待处理"移到"已声明"。

        豁免**只免惩罚，不免可见**：条目仍然进 ``result.allowed`` 并照原样
        输出（带理由）。把已知无害的条目藏起来，等于让下一个人重新踩一遍。
        """
        table = self._allowlist
        if not table:
            return

        kept: list[SourceReviewViolation] = []
        for v in result.violations:
            rule = table.match(_symbol_of(v), v.file)
            if rule is None:
                kept.append(v)
                continue
            v.allowed_reason = rule.reason
            result.allowed.append(v)
            if _is_register_level(v):
                result.registers_allowed += 1
        if len(kept) != len(result.violations):
            result.violations = kept
            result.passed = not kept

        # warning 同样接受豁免 —— 「这处我核对过了，别再提示」
        kept_w: list[SourceReviewViolation] = []
        for w in result.warnings:
            rule = table.match(_symbol_of(w), w.file)
            if rule is None:
                kept_w.append(w)
                continue
            w.allowed_reason = rule.reason
            result.allowed.append(w)
            if _is_register_level(w):
                result.registers_allowed += 1
        result.warnings = kept_w

    def _log_verdict(self, result: SourceReviewResult) -> None:
        """一行结论，**必须能直接落到源码某一行**。

        旧写法只有 ``Source review: FAIL (registers 7/9)``：读这行的人知道
        有两条没解析，但不知道是哪两条、在哪个文件 —— 只能自己写脚本重跑
        一遍。汇总行不带落点，等于只报了个数。
        """
        gaps = (f"，{result.kb_gaps} 条未收录不判定"
                if result.kb_gaps else "")
        allowed = f"，已豁免 {len(result.allowed)} 条" if result.allowed else ""
        # 分母里剔除「没判定过的」：知识库缺口 + 已声明豁免。这两类都混进
        # 分母的话，PASS 的文件会显示成 `registers 0/1`，读起来像失败。
        judged_regs = max(0, result.registers_checked - result.kb_gaps
                          - result.registers_allowed)
        counters = (f"registers {result.registers_resolved}/{judged_regs}"
                    f"{gaps}，"
                    f"fields {result.fields_resolved}/{result.fields_checked}")

        if result.passed:
            logger.debug("Source review: PASS（%s%s）", counters, allowed)
            return

        head = "; ".join(
            f"{_where(v)} {v.register}" for v in result.violations[:3])
        more = (f" 等 {len(result.violations)} 处"
                if len(result.violations) > 3 else "")
        logger.warning("Source review: FAIL（%s）—— 落点 %s%s",
                       counters, head, more)

    # ------------------------------------------------------------------
    # 三态判定：库命中 / 器件头有 / 两处都无
    # ------------------------------------------------------------------
    def _record_unresolved(self, result: SourceReviewResult, periph: str,
                           reg: str, line_text: str, line_num: int) -> None:
        """限定名在知识库里查不到 —— 这时才有资格谈「是不是写错了」。

        判据不能只有知识库。知识库按 SVD 建，SVD 未建模的寄存器（H743 实测
        约 100 条，如 `TIM2.RCR`）查不到；幻觉寄存器（`GPIOA.BOGUS`）也查
        不到。**只靠知识库时两者输出一字不差** —— 工具在「不知道」的时候用
        了「你错了」的语气，这是 2026-10-27 那条误判的根。

        器件头是独立证据：厂商随 CMSIS 发布、gcc 直接拿它编译。于是分三态：

          器件头有   → 芯片上有，是**知识库缺口** → warning（附器件头依据）
          器件头也没有 → 真幻觉 → error，阻断
          无器件头/无此实例 → 没有第二份证据 → warning，不下对错结论
        """
        truth = self._device_truth
        verdict = (truth.check(periph, reg)
                   if truth is not None else Verdict.UNAVAILABLE)
        symbol = f"{periph}.{reg}"

        if verdict == Verdict.PRESENT:
            struct = truth.struct_of(periph) or "?"
            result.kb_gaps += 1
            result.warnings.append(SourceReviewViolation(
                register=symbol,
                line=line_num,
                line_text=line_text,
                severity="warning",
                kb_gap=True,
                evidence=f"器件头 {truth.source}: {struct}.{reg}",
                reason=(f"知识库未收录 '{symbol}' —— 但芯片上有这个寄存器"),
                suggestion=("源码没错，是知识库缺这一条（SVD 未建模）。"
                            "gcc 能编译即说明名称正确；"
                            "可在 board.yaml 同目录放 .ff-review.yaml 声明豁免"
                            "以免每次重复提示。"),
            ))
            return

        if verdict == Verdict.ABSENT:
            struct = truth.struct_of(periph) or "?"
            result.violations.append(SourceReviewViolation(
                register=symbol,
                line=line_num,
                line_text=line_text,
                severity="error",
                evidence=f"器件头 {truth.source}: {struct} 无此成员",
                reason=(f"'{symbol}' 不存在：器件头里 {struct} 也没有 '{reg}'，"
                        f"知识库同样没有"),
                suggestion=(f"外设 {periph} 存在，但 '{reg}' 不是它的寄存器。"
                            f"用 'ff context <board> --topic {periph}' 列出真名。"),
            ))
            result.passed = False
            return

        # NO_INSTANCE / UNAVAILABLE：没有第二份证据，不下判决
        if verdict == Verdict.NO_INSTANCE:
            why = (f"器件头里没有名为 '{periph}' 的实例"
                   f"（可能是别的宏体系，如 DMA1_Stream0）")
        else:
            why = ("本机没有该芯片的 CMSIS 器件头，未做交叉验证"
                   "（`ff setup` 可装 SDK）")
        result.warnings.append(SourceReviewViolation(
            register=symbol,
            line=line_num,
            line_text=line_text,
            severity="warning",
            reason=(f"知识库没收录 '{symbol}'，且{why} —— "
                    f"既不能说它对，也不能说它错"),
            suggestion=(f"用 'ff context <board> --topic {periph}' 核对；"
                        f"或装好 SDK 后重跑，届时能给出确定结论。"),
        ))

    def _note_unknown_peripheral(self, result: SourceReviewResult,
                                  periph: str, reg: str, op: str,
                                  line_text: str, line_num: int,
                                  seen: set[tuple[str, str]]) -> None:
        """外设实例名不在知识库里。

        此前一律跳过：`GPIOZ->BSRR` 连 registers_checked 都不加 —— 源码里明明
        引用了一个不存在的 GPIO，审查什么都不说，又是一处信息截留。

        现在三档：
          ① 器件头认这颗外设，且按结构体名能回推到库里的组 → **同一颗外设的
             命名差异**（`IWDG1` → `IWDG_TypeDef` → 库组 `IWDG`），计入已解析
          ② 器件头认这颗外设，但库里没有对应组 → 知识库缺口 → warning
          ③ 器件头也不认 → 只陈述事实 + 两种可能，不替编译器下判决
        """
        if op != "->":
            return
        if (periph, reg) in seen:
            return

        truth = self._device_truth
        if truth is not None and truth.available:
            verdict = truth.check(periph, reg)
            if verdict == Verdict.PRESENT:
                seen.add((periph, reg))
                result.registers_checked += 1
                alias = self._alias_group(truth.struct_of(periph), reg)
                if alias:
                    # 器件头（实例 → 类型 → 成员）与知识库（组名 → 寄存器）
                    # 两边都对上，这是确定的等价，不是猜测，因此计为已解析。
                    result.registers_resolved += 1
                    logger.debug("外设别名：%s.%s → %s.%s（器件头 %s）",
                                 periph, reg, alias, reg, truth.source)
                else:
                    struct = truth.struct_of(periph) or "?"
                    result.kb_gaps += 1
                    result.warnings.append(SourceReviewViolation(
                        register=f"{periph}.{reg}",
                        line=line_num,
                        line_text=line_text,
                        severity="warning",
                        kb_gap=True,
                        evidence=f"器件头 {truth.source}: {struct}.{reg}",
                        reason=(f"外设 '{periph}' 不在知识库里，但芯片上有 —— "
                                f"知识库按另一套命名收录"),
                        suggestion=(f"源码可编译即可。用 'ff context <board> "
                                    f"--topic {struct} ' 查库里的真名。"),
                    ))
                return

        owner = self._knowledge_base.lookup_register(reg)
        if owner is None:
            return
        seen.add((periph, reg))
        result.registers_checked += 1
        group = owner.get("_group") or "?"
        result.warnings.append(SourceReviewViolation(
            register=f"{periph}.{reg}",
            line=line_num,
            line_text=line_text,
            severity="warning",
            reason=(f"外设名 '{periph}' 不在知识库里 —— "
                    f"本次未审查它的寄存器（'{reg}' 在库里属于 {group}）"),
            suggestion=(f"两种可能：(a) {periph} 是 CMSIS 实例名而"
                        f"知识库按另一套命名收录（DMA1_Stream0 这类，属知识库"
                        f"缺口）；(b) 外设名写错，gcc 会拒。"
                        f"用 'ff context <board> --topic {group}' 核对。"),
        ))

    def _alias_group(self, struct: str | None, reg: str) -> str | None:
        """器件头结构体名 → 知识库组名。查得到该寄存器才返回。"""
        if not struct:
            return None
        base = struct[:-len("_TypeDef")] if struct.endswith("_TypeDef") else struct
        if self._knowledge_base.lookup_register_qualified(base, reg):
            return base
        return None

    @staticmethod
    def _strip_strings(line: str) -> str:
        """Strip string literals and char literals from a line.

        Replaces "..." and '...' with spaces so register-like names
        inside strings don't trigger false positives.
        """
        # Replace quoted strings with spaces (preserve length for line numbers)
        result = re.sub(r'"([^"\\]|\\.)*"', lambda m: " " * len(m.group()), line)
        result = re.sub(r"'([^'\\]|\\.)*'", lambda m: " " * len(m.group()), result)
        return result

    def _resolve_field(self, field_name: str) -> bool:
        """Try to resolve a bit-field name against the reference library.

        Checks:
        1. Is it a known field in any register?
        2. Is it a port bit name (PORTB7, DDRB3, PINC5)?
        3. Is it a common AVR macro (_BV equivalent)?
        """
        field_upper = field_name.upper()

        # Strategy 1: 位域全名索引（O(1)）。
        # 曾经这里是「遍历所有寄存器、再遍历每个寄存器的位」，STM32 上是
        # 1761 × 平均 6 位，而每个位引用都要重扫一遍 —— 审查一度是全流程里
        # 最慢的一段。索引在 load_reference 时建好，名字就是 CMSIS 位宏名
        # （``USART_CR1_TE``），比遍历更准也更快。
        if self._knowledge_base.lookup_field(field_upper):
            return True

        # Strategy 2: Port bit name pattern (PORTB7, DDRB3, PINC5)
        port_match = re.match(r'^(PORT|DDR|PIN)([A-L])(\d)$', field_upper)
        if port_match:
            base_reg = port_match.group(1) + port_match.group(2)
            if self._knowledge_base.lookup_register(base_reg):
                return True

        # Strategy 3: Common AVR field macros that are always valid
        common_fields = {
            "SE", "SM0", "SM1", "SM2",  # Sleep mode
            "WDE", "WDCE", "WDP0", "WDP1", "WDP2", "WDP3",  # Watchdog
            "INT0", "INT1", "INT2", "INT3", "INT4", "INT5", "INT6", "INT7",
            "ISC00", "ISC01", "ISC10", "ISC11",  # External interrupt
            "ADEN", "ADSC", "ADATE", "ADIF", "ADIE",  # ADC
            "ADPS0", "ADPS1", "ADPS2", "REFS0", "REFS1", "ADLAR", "MUX0",
            "MUX1", "MUX2", "MUX3", "MUX4",
            "SPE", "SPIE", "MSTR", "CPOL", "CPHA", "SPR0", "SPR1",  # SPI
            "SPIF", "WCOL", "SPI2X", "DORD",
            "TWEN", "TWIE", "TWINT", "TWEA", "TWSTA", "TWSTO", "TWWC",  # TWI
            "TWPS0", "TWPS1", "TWS3", "TWS4", "TWS5", "TWS6", "TWS7",
            "COM0A0", "COM0A1", "COM0B0", "COM0B1",  # Timer
            "WGM00", "WGM01", "WGM02", "WGM10", "WGM11", "WGM12", "WGM13",
            "CS00", "CS01", "CS02", "CS10", "CS11", "CS12",
            "CS20", "CS21", "CS22",
            "FOC0A", "FOC0B", "FOC1A", "FOC1B", "FOC2A", "FOC2B",
            "OCF0A", "OCF0B", "OCF1A", "OCF1B", "OCF2A", "OCF2B",
            "TOV0", "TOV1", "TOV2", "TOV3", "TOV4", "TOV5",
            "TOIE0", "TOIE1", "TOIE2", "TOIE3", "TOIE4", "TOIE5",
            "OCIE0A", "OCIE0B", "OCIE1A", "OCIE1B", "OCIE1C",
            "OCIE2A", "OCIE2B", "OCIE3A", "OCIE3B", "OCIE3C",
            "OCIE4A", "OCIE4B", "OCIE4C", "OCIE5A", "OCIE5B", "OCIE5C",
            "ICIE1", "ICIE3", "ICIE4", "ICIE5",
            "ICES1", "ICES3", "ICES4", "ICES5",
            "ACME", "ACIS0", "ACIS1", "ACBG", "ACD", "ACO", "ACI", "ACIE",
            "EERE", "EEMWE", "EEWE", "EERIE",
            "CLKPCE", "CLKPS0", "CLKPS1", "CLKPS2", "CLKPS3",
            "EXCLK", "AS0", "TCN0UB", "OCR0UB", "TCR0BUB", "TCR0AUB",
            "PRADC", "PRUSART0", "PRUSART1", "PRUSART2", "PRUSART3",
            "PRTIM0", "PRTIM1", "PRTIM2", "PRTIM3", "PRTIM4", "PRTIM5",
            "PRSPI", "PRTWI", "PRTWI0",
            "JTRF", "JTD", "ISC2", "IVCE", "IVSEL",
            "SMCR", "MCUCR", "MCUSR", "WDRF", "BORF", "EXTRF", "PORF",
        }
        if field_upper in common_fields:
            return True

        return False

    def validate_file(self, filepath: str | Any) -> SourceReviewResult:
        """Validate a source file.

        Args:
            filepath: Path to the C/C++ source file.

        Returns:
            SourceReviewResult.
        """
        from pathlib import Path
        p = Path(filepath)
        if not p.exists():
            return SourceReviewResult(
                passed=False,
                violations=[SourceReviewViolation(
                    register="",
                    severity="error",
                    reason=f"File not found: {filepath}",
                )],
            )

        source = p.read_text(encoding="utf-8", errors="replace")
        # 传**相对路径**（能带上子目录），不是 basename：同目录下可能有两份
        # 同名头文件，只给基名等于制造歧义。
        label = str(p)
        try:
            label = p.resolve().as_posix()
        except OSError:
            pass
        return self.validate(source, filename=label)


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------


def _symbol_of(item: SourceReviewViolation) -> str:
    """违规条目 → 可用于豁免匹配的符号名（``SCB.CFSR`` / ``GPIO_MODER_BOGUS``）。"""
    return f"{item.register}.{item.field}" if item.field else item.register


def _where(item: SourceReviewViolation) -> str:
    """``file:line`` 形态的落点。没有文件名时退化为行号。"""
    if item.file and item.line:
        return f"{item.file}:{item.line}"
    return f"line {item.line}" if item.line else "<unknown>"


def _is_register_level(item: SourceReviewViolation) -> bool:
    """这条豁免占的是 registers 计数还是 fields 计数。

    外设级条目形如 ``GPIOA.BSRRR``（register 本身带点），位宏条目是裸名
    （``GPIO_MODER_BOGUS``）。两者都算进 registers 计数的只有前者。
    """
    return bool(item.register) and "." in item.register and not item.field
