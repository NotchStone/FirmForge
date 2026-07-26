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
_REGISTER_ASSIGN_RE = re.compile(
    r'\b([A-Z][A-Z0-9_]{2,})\s*' + _ASSIGN_OPS
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
class SourceReviewViolation:
    """A single source review violation or warning.

    Attributes:
        register: Register or field name found in code.
        field: Field name if applicable (empty for register-level).
        line: 1-based line number in source code.
        line_text: The actual source line text.
        severity: "error" (blocks compilation) or "warning" (informational).
        reason: Human-readable explanation of the violation.
        suggestion: How to fix the issue.
    """

    register: str
    field: str = ""
    line: int = 0
    line_text: str = ""
    severity: str = "error"
    reason: str = ""
    suggestion: str = ""

    def __str__(self) -> str:
        loc = f"line {self.line}" if self.line else "unknown line"
        target = f"{self.register}.{self.field}" if self.field else self.register
        return f"[{self.severity.upper()}] {loc}: {target} -- {self.reason}"


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
    """

    passed: bool = True
    violations: list[SourceReviewViolation] = field(default_factory=list)
    warnings: list[SourceReviewViolation] = field(default_factory=list)
    registers_checked: int = 0
    registers_resolved: int = 0
    fields_checked: int = 0
    fields_resolved: int = 0

    def summary(self) -> str:
        """Human-readable summary string."""
        lines = [
            f"Code Review: {'PASS' if self.passed else 'FAIL'}",
            f"  Registers: {self.registers_resolved}/{self.registers_checked} resolved",
            f"  Fields: {self.fields_resolved}/{self.fields_checked} resolved",
            f"  Errors: {len(self.violations)}",
            f"  Warnings: {len(self.warnings)}",
        ]
        for v in self.violations:
            lines.append(f"  {v}")
        for w in self.warnings:
            lines.append(f"  {w}")
        return "\n".join(lines)


class SourceReviewer:
    """Source code reviewer — fast pre-build structural scan.

    Implements 规划 §2.7 引用门禁 Code Review:
    - Generated register/bitfield values must carry $ref to knowledge base
    - Unresolvable references are blocked before compilation
    - Prevents "hallucinated register" and "wrong clock tree" errors

    Args:
        knowledge_base: KnowledgeBase instance with reference library loaded.
    """

    def __init__(self, knowledge_base: KnowledgeBase) -> None:
        self._knowledge_base = knowledge_base

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

    @classmethod
    def for_board(cls, knowledge_base: KnowledgeBase,
                  paradigm: str = "arduino", chip: str | None = None
                  ) -> SourceReviewer:
        """Create a validator pre-loaded with the correct register library.

        Routes to the platform-specific register reference based on paradigm:
          - arduino → knowledge/reference/avr/<chip>/registers.json
          - stc     → knowledge/reference/stc/<chip>/registers.json
          - esp_idf → knowledge/reference/esp32/<chip>/registers.json
          - register → same as platform-default

        Falls back to platform-level registers.json if chip directory
        doesn't exist.
        """
        platform_map = {
            "arduino": "avr",
            "stc": "stc",
            "esp_idf": "esp32",
            "register": "avr",  # default
        }
        platform = platform_map.get(paradigm, "avr")
        knowledge_base.load_reference(platform, chip=chip)
        return cls(knowledge_base)

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
        lines = source_code.splitlines()

        # Track already-checked items to avoid duplicates
        seen_registers: set[tuple[str, int]] = set()
        seen_fields: set[tuple[str, int]] = set()

        for line_num, line in enumerate(lines, start=1):
            stripped = self._strip_strings(line).strip()

            # Skip comments, preprocessor, and empty lines
            if not stripped:
                continue
            if stripped.startswith("//") or stripped.startswith("#"):
                continue
            if stripped.startswith("/*") or stripped.startswith("*"):
                continue

            # --- Phase 1: Extract bit-field references FIRST ---
            # This lets us exclude them from register scanning
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
                if key in seen_fields:
                    continue
                seen_fields.add(key)

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

            # --- Phase 2: Find register names in assignment context ---
            for match in _REGISTER_ASSIGN_RE.finditer(stripped):
                reg_name = match.group(1)

                # Skip known non-register identifiers
                if reg_name in _KNOWN_NON_REGISTERS:
                    continue

                # Skip user-defined names (contain underscore — AVR registers never do)
                if "_" in reg_name:
                    continue

                # Skip if this is actually a field name on this line
                if reg_name.upper() in field_names_on_line:
                    continue

                # Skip common C keywords/types that might match
                if reg_name.lower() in ("return", "while", "break", "continue"):
                    continue

                key = (reg_name, line_num)
                if key in seen_registers:
                    continue
                seen_registers.add(key)

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

            # --- Phase 3: Broader scan for register-like identifiers ---
            # This catches register reads (not assignments) like:
            #   if (UCSR0A & (1 << UDRE0))
            #   val = PINB;
            #
            # Strip string literals first to avoid matching register-like
            # names that appear inside strings (e.g. "ADC Channel:")
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
                if (ident, line_num) in seen_registers:
                    continue
                if ident.upper() in field_names_on_line:
                    continue

                # Skip if not register-like (must start with a known prefix)
                if not ident.upper().startswith(_REG_PREFIXES):
                    continue

                # Skip common false positives
                if ident in ("ISR", "SIGNAL", "DEFINE", "INCLUDE", "PRAGMA",
                             "F_CPU", "LED_BUILTIN"):
                    continue

                key = (ident, line_num)
                if key in seen_registers:
                    continue
                seen_registers.add(key)

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

        logger.info("Source review: %s (registers %d/%d, fields %d/%d)",
                     "PASS" if result.passed else "FAIL",
                     result.registers_resolved, result.registers_checked,
                     result.fields_resolved, result.fields_checked)

        return result

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

        # Strategy 1: Check all registers for a matching field
        for reg_entry in self._knowledge_base.get_all_registers().values():
            for fld in reg_entry.get("fields", []):
                if fld.get("name", "").upper() == field_upper:
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
        return self.validate(source, filename=str(p.name))
