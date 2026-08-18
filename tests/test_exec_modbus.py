"""Tests for _exec_modbus — frame construction, decode, error paths."""

import pytest

from firmforge.core.pipeline_runner import _exec_modbus
from firmforge.tools.modbus_utils import modbus_crc


class MockSer:
    """Fake serial object recording writes, returning preset read data."""
    def __init__(self, response: bytes = b""):
        self.response = response
        self.written: list[bytes] = []

    def write(self, data: bytes):
        self.written.append(data)

    def read(self, size: int = 256):
        return self.response


def _resp_frame(payload_hex: str) -> bytes:
    pdu = bytes.fromhex(payload_hex)
    return pdu + modbus_crc(pdu).to_bytes(2, "little")


@pytest.fixture(autouse=True)
def _clean_queues():
    """Empty the module-level modbus queues before each test."""
    from firmforge.adapters import panel_service as ps
    for q in (ps.get_modbus_request_queue(), ps.get_modbus_response_queue()):
        while True:
            try:
                q.get_nowait()
            except Exception:
                break
    yield
    for q in (ps.get_modbus_request_queue(), ps.get_modbus_response_queue()):
        while True:
            try:
                q.get_nowait()
            except Exception:
                break


def _run(ser, mb: dict):
    from firmforge.adapters import panel_service as ps
    ps.get_modbus_request_queue().put({"mb": mb})
    tx = [0]; rx = [0]
    _exec_modbus(ser, tx, rx)
    return ps.get_modbus_response_queue().get(timeout=1), tx[0], rx[0]


class TestExecModbus:
    def test_fc03_success_decodes_regs(self):
        ser = MockSer(_resp_frame("01 03 06 03 E8 03 E9 03 EA"))
        resp, tx, rx = _run(ser, {"slave": 1, "fc": 3, "addr": 0, "count": 3})
        assert resp["crc_ok"] is True
        assert resp["regs"] == [1000, 1001, 1002]
        assert tx == 8 and rx == 11

    def test_fc06_frame_is_8_bytes(self):
        ser = MockSer(_resp_frame("01 06 00 00 12 34"))
        _run(ser, {"slave": 1, "fc": 6, "addr": 0, "count": 0, "data": "4660"})
        sent = ser.written[0]
        # Regression: was 10 bytes with an extra 0x0000 word.
        assert len(sent) == 8
        assert sent[0] == 1 and sent[1] == 6
        assert sent[2:4] == b"\x00\x00"  # addr
        assert sent[4:6] == b"\x12\x34"  # value 0x1234 = 4660

    def test_fc16_frame_layout(self):
        ser = MockSer(_resp_frame("01 10 00 00 00 02"))
        _run(ser, {"slave": 1, "fc": 16, "addr": 0, "count": 2, "data": "11,22"})
        sent = ser.written[0]
        assert sent[1] == 0x10
        assert sent[4:6] == b"\x00\x02"  # count
        assert sent[6] == 4              # byte count
        assert sent[7:11] == b"\x00\x0B\x00\x16"  # 11, 22

    def test_no_request_returns_immediately(self):
        from firmforge.adapters import panel_service as ps
        ser = MockSer()
        tx = [0]; rx = [0]
        _exec_modbus(ser, tx, rx)
        assert ps.get_modbus_response_queue().empty()

    def test_ser_none_returns_error(self):
        resp, tx, rx = _run(None, {"slave": 1, "fc": 3, "addr": 0, "count": 1})
        assert "serial closed" in resp["error"]

    def test_slave_out_of_range(self):
        ser = MockSer()
        resp, _, _ = _run(ser, {"slave": 300, "fc": 3, "addr": 0, "count": 1})
        assert "out of range" in resp["error"]
        assert ser.written == []  # nothing sent

    def test_bad_hex_value_reports_error(self):
        ser = MockSer()
        resp, _, _ = _run(ser, {"slave": 1, "fc": 6, "addr": 0, "data": "zzz"})
        assert "error" in resp  # int() conversion failed -> caught
