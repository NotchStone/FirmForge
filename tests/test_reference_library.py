"""Tests for the AVR register reference library (knowledge/reference/avr/).

Tests loading atmega2560/registers.json and pins.json, verifying
register/pin/baud-rate lookups, and Schema compliance.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from firmforge.knowledge.knowledge_base import KnowledgeBase


# Fixtures ------------------------------------------------------------------

@pytest.fixture
def kb() -> KnowledgeBase:
    """KnowledgeBase with AVR reference library loaded."""
    kb = KnowledgeBase()
    kb.load_reference("avr", chip="atmega2560")
    return kb


# Register loading tests ----------------------------------------------------

class TestRegisterLoading:
    def test_load_reference_succeeds(self):
        kb = KnowledgeBase()
        assert kb.load_reference("avr", chip="atmega2560") is True

    def test_load_reference_nonexistent_platform(self):
        kb = KnowledgeBase()
        assert kb.load_reference("nonexistent") is False

    def test_registers_indexed(self, kb: KnowledgeBase):
        stats = kb.stats()
        assert stats["total_registers_indexed"] >= 57  # 33 GPIO + 24 USART
        assert stats["reference_platforms_loaded"] == ["avr"]

    def test_pins_indexed(self, kb: KnowledgeBase):
        stats = kb.stats()
        assert stats["total_pins_indexed"] == 70  # Mega2560 digital pins 0-69
        assert "arduino_mega" in stats["pin_maps_loaded"]

    def test_registers_json_valid_json(self):
        reg_path = Path("knowledge/reference/avr/atmega2560/registers.json")
        with open(reg_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["mcu"] == "ATmega2560"
        assert data["platform"] == "arduino"
        assert "register_groups" in data
        assert "gpio" in data["register_groups"]
        assert "usart" in data["register_groups"]

    def test_pins_json_valid_json(self):
        pin_path = Path("knowledge/reference/avr/atmega2560/pins.json")
        with open(pin_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["board"] == "arduino_mega"
        assert data["mcu"] == "ATmega2560"
        assert len(data["pins"]) == 70
        assert data["led_builtin"]["arduino_pin"] == 13


# Register lookup tests -----------------------------------------------------

class TestRegisterLookup:
    def test_lookup_portb(self, kb: KnowledgeBase):
        reg = kb.lookup_register("PORTB")
        assert reg is not None
        assert reg["address"] == "0x25"  # memory-mapped
        assert "description" in reg

    def test_lookup_ddrb(self, kb: KnowledgeBase):
        reg = kb.lookup_register("DDRB")
        assert reg is not None
        assert reg["address"] == "0x24"

    def test_lookup_pinb(self, kb: KnowledgeBase):
        reg = kb.lookup_register("PINB")
        assert reg is not None
        assert reg["address"] == "0x23"

    def test_lookup_ucsr0a(self, kb: KnowledgeBase):
        reg = kb.lookup_register("UCSR0A")
        assert reg is not None
        assert reg["address"] == "0xC0"
        # Check key fields
        field_names = [f["name"] for f in reg["fields"]]
        assert "RXC0" in field_names
        assert "TXC0" in field_names
        assert "UDRE0" in field_names

    def test_lookup_ucsr0b(self, kb: KnowledgeBase):
        reg = kb.lookup_register("UCSR0B")
        assert reg is not None
        assert reg["address"] == "0xC1"
        field_names = [f["name"] for f in reg["fields"]]
        assert "TXEN0" in field_names
        assert "RXEN0" in field_names
        assert "RXCIE0" in field_names

    def test_lookup_udr0(self, kb: KnowledgeBase):
        reg = kb.lookup_register("UDR0")
        assert reg is not None
        assert reg["address"] == "0xC6"

    def test_lookup_ubrr0l(self, kb: KnowledgeBase):
        reg = kb.lookup_register("UBRR0L")
        assert reg is not None
        assert reg["address"] == "0xC4"

    def test_lookup_ubrr0h(self, kb: KnowledgeBase):
        reg = kb.lookup_register("UBRR0H")
        assert reg is not None
        assert reg["address"] == "0xC5"

    def test_lookup_nonexistent_register(self, kb: KnowledgeBase):
        assert kb.lookup_register("PORTZ") is None
        assert kb.lookup_register("UCSR9A") is None
        assert kb.lookup_register("FAKE") is None

    def test_lookup_case_insensitive(self, kb: KnowledgeBase):
        assert kb.lookup_register("portb") is not None
        assert kb.lookup_register("PortB") is not None
        assert kb.lookup_register("PORTB") is not None

    def test_all_gpio_registers_present(self, kb: KnowledgeBase):
        """All 11 GPIO ports × 3 registers = 33 registers.
        ATmega2560 has ports A-G, H, J-L (skips I to avoid confusion with 1).
        """
        ports = "ABCDEFGHJKL"  # No 'I' — Microchip skips it
        for port in ports:
            assert kb.lookup_register(f"PORT{port}") is not None, f"PORT{port} missing"
            assert kb.lookup_register(f"DDR{port}") is not None, f"DDR{port} missing"
            assert kb.lookup_register(f"PIN{port}") is not None, f"PIN{port} missing"

    def test_all_usart_registers_present(self, kb: KnowledgeBase):
        """All 4 USARTs × 6 registers = 24 registers."""
        for n in range(4):
            assert kb.lookup_register(f"UDR{n}") is not None, f"UDR{n} missing"
            assert kb.lookup_register(f"UCSR{n}A") is not None, f"UCSR{n}A missing"
            assert kb.lookup_register(f"UCSR{n}B") is not None, f"UCSR{n}B missing"
            assert kb.lookup_register(f"UCSR{n}C") is not None, f"UCSR{n}C missing"
            assert kb.lookup_register(f"UBRR{n}L") is not None, f"UBRR{n}L missing"
            assert kb.lookup_register(f"UBRR{n}H") is not None, f"UBRR{n}H missing"

    def test_register_has_description(self, kb: KnowledgeBase):
        """Every register should have a description."""
        for reg_name in ["PORTB", "UCSR0A", "UDR0", "UBRR0L"]:
            reg = kb.lookup_register(reg_name)
            assert reg is not None
            assert "description" in reg, f"{reg_name} missing description"
            assert reg["description"], f"{reg_name} empty description"


# Register field lookup tests -----------------------------------------------

class TestRegisterFieldLookup:
    def test_lookup_field_rxen0(self, kb: KnowledgeBase):
        fld = kb.lookup_register_field("UCSR0B", "RXEN0")
        assert fld is not None
        assert fld["bit"] == 4
        assert "Receiver Enable" in fld["description"]

    def test_lookup_field_txen0(self, kb: KnowledgeBase):
        fld = kb.lookup_register_field("UCSR0B", "TXEN0")
        assert fld is not None
        assert fld["bit"] == 3

    def test_lookup_field_udre0(self, kb: KnowledgeBase):
        fld = kb.lookup_register_field("UCSR0A", "UDRE0")
        assert fld is not None
        assert fld["bit"] == 5

    def test_lookup_field_ucsr0a(self, kb: KnowledgeBase):
        """USART registers still have per-bit fields."""
        fld = kb.lookup_register_field("UCSR0A", "TXC0")
        assert fld is not None
        assert fld["bit"] == 6
        assert "Transmit" in fld["description"]

    def test_lookup_field_nonexistent(self, kb: KnowledgeBase):
        assert kb.lookup_register_field("UCSR0B", "FAKE") is None
        assert kb.lookup_register_field("FAKE", "RXEN0") is None


# Pin lookup tests ----------------------------------------------------------

class TestPinLookup:
    def test_lookup_pin_13_led(self, kb: KnowledgeBase):
        pin = kb.lookup_pin(13)
        assert pin is not None
        assert pin["port"] == "B"
        assert pin["bit"] == 7
        assert pin["register"] == "PORTB"
        assert "LED_BUILTIN" in pin.get("special", "")

    def test_lookup_pin_0_rx0(self, kb: KnowledgeBase):
        pin = kb.lookup_pin(0)
        assert pin is not None
        assert pin["port"] == "E"
        assert "RXD0" in pin.get("special", "")

    def test_lookup_pin_1_tx0(self, kb: KnowledgeBase):
        pin = kb.lookup_pin(1)
        assert pin is not None
        assert pin["port"] == "E"
        assert "TXD0" in pin.get("special", "")

    def test_lookup_pin_out_of_range(self, kb: KnowledgeBase):
        assert kb.lookup_pin(70) is None
        assert kb.lookup_pin(-1) is None
        assert kb.lookup_pin(100) is None

    def test_all_70_pins_present(self, kb: KnowledgeBase):
        for p in range(70):
            assert kb.lookup_pin(p) is not None, f"Pin {p} missing"

    def test_pin_has_ref(self, kb: KnowledgeBase):
        for p in [0, 13, 53, 69]:
            pin = kb.lookup_pin(p)
            assert pin is not None
            assert "$ref" in pin


# Baud rate lookup tests ----------------------------------------------------

class TestBaudRateLookup:
    def test_lookup_9600_baud(self, kb: KnowledgeBase):
        baud = kb.lookup_baud_rate(9600)
        assert baud is not None
        assert baud["ubrr"] == 103
        assert baud["ubrr_hex"] == "0x67"

    def test_lookup_115200_baud(self, kb: KnowledgeBase):
        baud = kb.lookup_baud_rate(115200)
        assert baud is not None
        assert baud["ubrr"] == 8

    def test_lookup_nonexistent_baud(self, kb: KnowledgeBase):
        assert kb.lookup_baud_rate(12345) is None


# List registers tests ------------------------------------------------------

class TestListRegisters:
    def test_list_all_registers(self, kb: KnowledgeBase):
        regs = kb.list_registers()
        assert len(regs) >= 57

    def test_list_gpio_registers(self, kb: KnowledgeBase):
        regs = kb.list_registers(group="gpio")
        assert len(regs) == 33  # 11 ports × 3

    def test_list_usart_registers(self, kb: KnowledgeBase):
        regs = kb.list_registers(group="usart")
        assert len(regs) == 26  # 4 USARTs × 6 + 2 UBRR 16-bit aliases

    def test_list_nonexistent_group(self, kb: KnowledgeBase):
        regs = kb.list_registers(group="nonexistent")
        assert regs == []
