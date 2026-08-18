"""Tests for firmforge.tools.modbus_utils — CRC, frame encode, response decode."""

import pytest

from firmforge.tools.modbus_utils import (
    modbus_crc,
    modbus_decode_response,
    modbus_encode_frame,
)


class TestModbusCrc:
    def test_crc_known_vector(self):
        # Standard Modbus RTU CRC check: "01 03 00 00 00 01" -> CRC 0x0A84 (LE: 84 0A)
        assert modbus_crc(bytes.fromhex("01 03 00 00 00 01")) == 0x0A84

    def test_crc_empty(self):
        assert modbus_crc(b"") == 0xFFFF

    def test_crc_deterministic(self):
        data = bytes.fromhex("01 06 00 00 12 34")
        assert modbus_crc(data) == modbus_crc(data)


class TestModbusEncodeFrame:
    def test_fc03_read_frame(self):
        # slave=1 fc=03 addr=0 count=5 -> 8 bytes total (6 PDU + 2 CRC)
        frame = modbus_encode_frame(1, 3, 0, count=5)
        assert len(frame) == 8
        assert frame[0] == 1 and frame[1] == 3
        assert frame[2:4] == b"\x00\x00"   # addr
        assert frame[4:6] == b"\x00\x05"   # count
        assert modbus_crc(frame[:-2]) == int.from_bytes(frame[-2:], "little")

    def test_fc04_read_frame(self):
        frame = modbus_encode_frame(1, 4, 3, count=10)
        assert len(frame) == 8
        assert frame[1] == 4
        assert frame[2:4] == b"\x00\x03"
        assert frame[4:6] == b"\x00\x0a"

    def test_fc06_write_single(self):
        # Correct FC06: slave+fc+addr+value = 6B PDU + 2B CRC = 8B total.
        # Regression: previously packed an extra 0x0000 word (10B frame).
        frame = modbus_encode_frame(1, 6, 0, values=[0x1234])
        assert len(frame) == 8, f"FC06 frame should be 8 bytes, got {len(frame)}"
        assert frame[2:4] == b"\x00\x00"   # addr
        assert frame[4:6] == b"\x12\x34"   # value
        assert modbus_crc(frame[:-2]) == int.from_bytes(frame[-2:], "little")

    def test_fc06_with_count_ignored(self):
        frame = modbus_encode_frame(1, 6, 7, count=99, values=[0xABCD])
        assert frame[2:4] == b"\x00\x07"
        assert frame[4:6] == b"\xAB\xCD"

    def test_fc16_write_multiple(self):
        frame = modbus_encode_frame(1, 16, 0, values=[0x0001, 0x0002, 0x0003])
        # PDU: 1+1+2+2+1+6 = 13 bytes + 2 CRC = 15
        assert len(frame) == 15
        assert frame[1] == 0x10
        assert frame[4:6] == b"\x00\x03"   # count
        assert frame[6] == 6               # byte count
        assert frame[7:9] == b"\x00\x01"
        assert frame[9:11] == b"\x00\x02"
        assert frame[11:13] == b"\x00\x03"
        assert modbus_crc(frame[:-2]) == int.from_bytes(frame[-2:], "little")

    def test_unsupported_fc_raises(self):
        with pytest.raises(ValueError):
            modbus_encode_frame(1, 0x2B, 0)


class TestModbusDecodeResponse:
    def _frame(self, payload_hex: str) -> bytes:
        pdu = bytes.fromhex(payload_hex)
        return pdu + modbus_crc(pdu).to_bytes(2, "little")

    def test_decode_read_success(self):
        resp = self._frame("01 03 06 03 E8 03 E9 03 EA")
        regs, err = modbus_decode_response(resp)
        assert err == ""
        assert regs == [0x03E8, 0x03E9, 0x03EA]

    def test_decode_exception(self):
        resp = self._frame("01 83 02")  # Illegal Data Address
        regs, err = modbus_decode_response(resp)
        assert regs == []
        assert "Exception 2" in err

    def test_decode_crc_error(self):
        resp = bytes.fromhex("01 03 02 12 34 00 00")  # wrong CRC
        regs, err = modbus_decode_response(resp)
        assert regs == []
        assert err == "CRC error"

    def test_decode_too_short(self):
        regs, err = modbus_decode_response(b"\x01\x03")
        assert regs == []
        assert err == "Response too short"

    def test_decode_write_echo(self):
        resp = self._frame("01 06 00 00 12 34")
        regs, err = modbus_decode_response(resp)
        assert err == ""
        assert regs == [0]  # echo addr
