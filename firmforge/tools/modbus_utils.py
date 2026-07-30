"""Modbus RTU utility functions: CRC-16, frame assembly, response decoding."""

import struct


def modbus_crc(data: bytes) -> int:
    """Compute Modbus RTU CRC-16 (polynomial 0xA001)."""
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc


def modbus_encode_frame(slave: int, func: int, addr: int,
                        count: int = 0, values: list[int] | None = None) -> bytes:
    """Build a Modbus RTU frame (PDU + CRC)."""
    if func in (6, 16) and values:
        frame = struct.pack(">BBHH", slave, func, addr, count if func != 6 else 0)
        if func == 6 and values:
            frame += struct.pack(">H", values[0])
        elif func == 16 and values:
            frame += struct.pack(">H", len(values))
            frame += struct.pack(">B", len(values) * 2)
            frame += struct.pack(">" + "H" * len(values), *values)
    else:
        frame = struct.pack(">BBHH", slave, func, addr, count)
    frame += struct.pack("<H", modbus_crc(frame))
    return frame


def modbus_decode_response(resp: bytes, addr_base: int = 0
                           ) -> tuple[list[int], str]:
    """Decode a Modbus response.

    Returns (register_values, error_message).
    - On success: ([val1, val2, ...], "")
    - On exception: ([], "Exception: XX (description)")
    - On invalid: ([], "CRC error" or "Invalid response")
    """
    if len(resp) < 5:
        return [], "Response too short"

    # CRC check
    stored_crc = struct.unpack("<H", resp[-2:])[0]
    if modbus_crc(resp[:-2]) != stored_crc:
        return [], "CRC error"

    slave = resp[0]
    func = resp[1]

    # Exception response
    if func & 0x80:
        exc_code = resp[2]
        msgs = ["Illegal Function", "Illegal Data Address",
                "Illegal Data Value", "Slave Failure",
                "Acknowledge", "Slave Busy"]
        desc = msgs[exc_code - 1] if 1 <= exc_code <= len(msgs) else "Unknown"
        return [], f"Exception {exc_code}: {desc}"

    # Read response (FC03, FC04)
    if func in (3, 4) and len(resp) >= 5:
        byte_count = resp[2]
        data_bytes = resp[3:-2]
        if len(data_bytes) < byte_count:
            data_bytes = data_bytes + b"\x00" * (byte_count - len(data_bytes))
        regs = []
        for i in range(0, min(byte_count, len(data_bytes)), 2):
            regs.append((data_bytes[i] << 8) | (data_bytes[i + 1] if i + 1 < len(data_bytes) else 0))
        return regs, ""

    # Write response (FC06, FC16) - echo back the request
    if func in (6, 16) and len(resp) >= 6:
        echo_addr = (resp[2] << 8) | resp[3]
        return [echo_addr], ""

    return [], "Unknown response format"
