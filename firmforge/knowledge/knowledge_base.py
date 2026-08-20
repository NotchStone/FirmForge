"""KnowledgeBase -- unified chip knowledge query interface.

Loads chip-specific reference data: registers, pins, bit-fields.
Storage: JSON exact lookup per chip (knowledge/reference/<arch>/<chip>/).

Example:
    knowledge_base = KnowledgeBase()
    knowledge_base.load_reference("avr", chip="atmega2560")
    reg = knowledge_base.lookup_register("PORTB")
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class KnowledgeBase:
    """Unified knowledge query interface.

    Usage:
        knowledge_base = KnowledgeBase()
        knowledge_base.load_reference("avr", chip="atmega328p")

        # Look up PORTB register definition
        reg = knowbase.lookup_register("PORTB")
        print(reg["address"])  # "0x05"

        # Look up Arduino pin 13 → AVR port/pin
        pin = knowbase.lookup_pin(13)
        print(pin["register"])  # "PORTB"

        for r in results:
            print(f"[{r.score:.4f}] {r.source}: {r.hit.get('name', '?')}")
    """

    def __init__(self, knowledge_dir: Path | str | None = None) -> None:
        from firmforge.core.resources import knowledge_dir as _default_knowledge
        self._dir = Path(knowledge_dir) if knowledge_dir else _default_knowledge()
        # Reference library caches
        self._ref_cache: dict[str, dict[str, Any]] = {}  # platform -> registers.json
        self._register_index: dict[str, dict[str, Any]] = {}  # reg_name -> register entry
        self._pin_index: dict[int, dict[str, Any]] = {}  # arduino_pin -> pin entry
        self._pin_map_cache: dict[str, dict[str, Any]] = {}  # board_id -> pins_*.json

    # ------------------------------------------------------------------
    # Reference library (Stage 4, §3.2.1 P0-1 SVD映射 / P1-4 强类型引用)
    # ------------------------------------------------------------------

    def load_reference(self, platform: str = "avr",
                        chip: str | None = None) -> bool:
        """Load register + pin reference data for a chip.

        Path: knowledge/reference/<platform>/<chip>/registers.json
              knowledge/reference/<platform>/<chip>/pins.json

        chip parameter is required — chip-level directories are the standard.
        """
        if not chip:
            logger.warning("load_reference() needs chip parameter; no platform-level data")
            return False

        ref_dir = self._dir / "reference" / platform / chip.lower()
        if not ref_dir.exists():
            logger.warning("Reference directory not found: %s", ref_dir)
            return False

        loaded_any = False

        # Load registers.json
        reg_path = ref_dir / "registers.json"
        if reg_path.exists():
            with open(reg_path, "r", encoding="utf-8") as f:
                reg_data = json.load(f)
            self._ref_cache[platform] = reg_data

            # Build register index: name -> register entry
            for group_name, group in reg_data.get("register_groups", {}).items():
                for reg in group.get("registers", []):
                    name = reg.get("name", "")
                    if name:
                        reg_entry = dict(reg)
                        reg_entry["_group"] = group_name
                        reg_entry["_platform"] = platform
                        self._register_index[name.upper()] = reg_entry
                        logger.debug("Indexed register: %s @ %s",
                                     name, reg.get("address", "?"))

            logger.info("KnowledgeBase loaded %d registers from %s",
                         len(self._register_index), reg_path)
            loaded_any = True

        # Load pin mapping files (pins*.json)
        for pin_file in sorted(ref_dir.glob("pins*.json")):
            with open(pin_file, "r", encoding="utf-8") as f:
                pin_data = json.load(f)
            board_id = pin_data.get("board", pin_file.stem)
            self._pin_map_cache[board_id] = pin_data
            # Chip alias key: pins.json board label may differ from board_id
            # (e.g. arduino_uno vs arduino_328p) — allow chip-level lookup.
            self._pin_map_cache.setdefault(chip.lower(), pin_data)

            # Build pin index: arduino_pin -> pin entry
            # pins may be a list of entry dicts OR a dict keyed by pin name
            pins = pin_data.get("pins", [])
            pin_items = pins.values() if isinstance(pins, dict) else pins
            for pin_entry in pin_items:
                arduino_pin = pin_entry.get("arduino_pin", -1)
                if arduino_pin >= 0:
                    self._pin_index[arduino_pin] = pin_entry

            logger.info("KnowledgeBase loaded %d pins from %s (board=%s)",
                         len(pin_data.get("pins", [])), pin_file, board_id)
            loaded_any = True

        return loaded_any

    def lookup_register(self, reg_name: str) -> dict[str, Any] | None:
        """Exact register lookup by name.

        Args:
            reg_name: e.g. "PORTB", "UCSR0A", "DDRB"

        Returns:
            Register definition dict with fields, address, $ref, or None.
        """
        return self._register_index.get(reg_name.upper())

    def lookup_register_field(self, reg_name: str,
                               field_name: str) -> dict[str, Any] | None:
        """Look up a specific bit field within a register.

        Args:
            reg_name: Register name, e.g. "UCSR0B"
            field_name: Field name, e.g. "RXEN0"

        Returns:
            Field definition dict with bit, access, description, or None.
        """
        reg = self.lookup_register(reg_name)
        if not reg:
            return None
        for fld in reg.get("fields", []):
            if fld.get("name", "").upper() == field_name.upper():
                return fld
        return None

    def lookup_pin(self, arduino_pin: int) -> dict[str, Any] | None:
        """Look up Arduino pin number → AVR port/bit mapping.

        Args:
            arduino_pin: Arduino digital pin number (0-69 for Mega2560)

        Returns:
            Pin mapping dict with port, bit, register, ddr, pin_reg, $ref, or None.
        """
        return self._pin_index.get(arduino_pin)

    def get_pin_map(self, board_id: str) -> dict[str, Any]:
        """Get the full pin map for a board (read-only copy)."""
        return dict(self._pin_map_cache.get(board_id, {}))

    def get_all_registers(self) -> dict[str, dict[str, Any]]:
        """Get all loaded register entries (read-only snapshot)."""
        return dict(self._register_index)

    def lookup_baud_rate(self, baud: int,
                          board_id: str = "arduino_mega") -> dict[str, Any] | None:
        """Look up baud rate preset for a board.

        Args:
            baud: Baud rate (e.g. 9600, 115200)
            board_id: Board identifier for pin map lookup

        Returns:
            Baud rate preset dict with ubrr, ubrr_hex, error_pct, $ref, or None.
        """
        pin_map = self._pin_map_cache.get(board_id, {})
        presets = pin_map.get("baud_rate_presets", {})
        return presets.get(str(baud))

    def list_registers(self, group: str = "",
                        platform: str = "avr") -> list[dict[str, Any]]:
        """List all registers, optionally filtered by group.

        Args:
            group: Register group name (e.g. "gpio", "usart"). Empty = all.
            platform: Platform identifier

        Returns:
            List of register definition dicts.
        """
        ref_data = self._ref_cache.get(platform, {})
        groups = ref_data.get("register_groups", {})

        if group:
            return groups.get(group, {}).get("registers", [])

        result: list[dict[str, Any]] = []
        for g in groups.values():
            result.extend(g.get("registers", []))
        return result

    # Board knowledge (unchanged from Stage 2)
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def stats(self) -> dict[str, Any]:
        return {
            "platforms_loaded": list(self._ref_cache.keys()),
            "reference_platforms_loaded": list(self._ref_cache.keys()),
            "total_registers_indexed": len(self._register_index),
            "total_pins_indexed": len(self._pin_index),
            "pin_maps_loaded": list(self._pin_map_cache.keys()),
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

