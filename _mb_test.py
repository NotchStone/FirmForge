# -*- coding: utf-8 -*-
"""Modbus RTU slave verification: FC03 / FC04 / FC06 / FC16 + exceptions."""
import serial
import sys
import time

PORT = sys.argv[1] if len(sys.argv) > 1 else 'COM4'
BAUD = 9600
SLAVE = 1
PASS = 0
FAIL = 0


def crc16(data):
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def build_frame(fc, payload):
    body = bytes([SLAVE, fc]) + payload
    c = crc16(body)
    return body + bytes([c & 0xFF, c >> 8])


def check_crc(resp):
    exp = crc16(resp[:-2])
    got = resp[-2] | (resp[-1] << 8)
    return exp == got


def read_frame(ser, timeout=0.6):
    """Read exactly one Modbus response frame."""
    ser.timeout = timeout
    addr = ser.read(1)
    if not addr:
        return None
    fc = ser.read(1)
    if not fc:
        return None
    a, f = addr[0], fc[0]
    if f & 0x80:                       # exception frame: +3 bytes
        d = ser.read(3)
        return (a, f, d) if len(d) == 3 else None
    if f in (0x03, 0x04):              # read: +1 byte count + data + crc
        bc = ser.read(1)
        if not bc:
            return None
        d = ser.read(bc[0] + 2)
        return (a, f, bc + d) if len(d) == bc[0] + 2 else None
    if f in (0x06, 0x10):              # write: +6 bytes
        d = ser.read(6)
        return (a, f, d) if len(d) == 6 else None
    return None


def req(ser, fc, payload):
    ser.reset_input_buffer()
    ser.write(build_frame(fc, payload))
    return read_frame(ser)


def report(name, ok, extra=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  PASS  {name} {extra}")
    else:
        FAIL += 1
        print(f"  FAIL  {name} {extra}")


def open_port(retries=8, delay=2.0):
    for i in range(retries):
        try:
            s = serial.Serial(PORT, BAUD, timeout=1)
            print(f"[open] {PORT} opened (attempt {i + 1})")
            return s
        except serial.SerialException as e:
            print(f"[open] attempt {i + 1} failed: {e}")
            time.sleep(delay)
    return None


def main():
    ser = open_port()
    if ser is None:
        print(f"FATAL: cannot open {PORT}")
        sys.exit(1)
    time.sleep(2.5)                    # let UNO reset & print banner
    ser.reset_input_buffer()
    print(f"=== Modbus Slave test @ {PORT} ({BAUD} 8N1), addr={SLAVE} ===")

    # ---- FC03 Read Holding Registers ----
    print("[FC03] Read Holding Registers 0x0000-0x0004")
    resp = req(ser, 0x03, bytes([0x00, 0x00, 0x00, 0x05]))
    ok = resp and resp[0] == SLAVE and resp[1] == 0x03 and resp[2][0] == 10 and check_crc(resp[2])
    regs = [resp[2][1 + i * 2] << 8 | resp[2][2 + i * 2] for i in range(5)] if resp else []
    report("FC03 read 5 regs", ok, f"-> {[hex(r) for r in regs]}")
    report("FC03 reg[0]=0x1234", ok and regs and regs[0] == 0x1234)
    report("FC03 reg[1-4]=1001..1004", ok and regs and regs[1:5] == [1001, 1002, 1003, 1004])

    # ---- FC04 Read Input Registers ----
    print("[FC04] Read Input Registers 0x0000-0x0002 (ADC0-2)")
    resp = req(ser, 0x04, bytes([0x00, 0x00, 0x00, 0x03]))
    ok = resp and resp[0] == SLAVE and resp[1] == 0x04 and resp[2][0] == 6 and check_crc(resp[2])
    inp = [resp[2][1 + i * 2] << 8 | resp[2][2 + i * 2] for i in range(3)] if resp else []
    report("FC04 read 3 input regs", ok, f"ADC0-2 = {inp}")
    report("FC04 ADC<=1023 (10-bit)", ok and all(v <= 1023 for v in inp))

    print("[FC04] dynamic reg[4] (uptime ms, read twice)")
    r1 = req(ser, 0x04, bytes([0x00, 0x04, 0x00, 0x01]))
    time.sleep(0.15)
    r2 = req(ser, 0x04, bytes([0x00, 0x04, 0x00, 0x01]))
    v1 = (r1[2][1] << 8 | r1[2][2]) if r1 and r1[1] == 0x04 else -1
    v2 = (r2[2][1] << 8 | r2[2][2]) if r2 and r2[1] == 0x04 else -1
    report("FC04 uptime increments", 0 <= v1 < v2, f"{v1} -> {v2}")

    # ---- FC06 Write Single Register ----
    print("[FC06] Write Single Register 0x0005 = 0xABCD")
    resp = req(ser, 0x06, bytes([0x00, 0x05, 0xAB, 0xCD]))
    ok = resp and resp[0] == SLAVE and resp[1] == 0x06 and resp[2][:6] == bytes([0x00, 0x05, 0xAB, 0xCD]) and check_crc(resp[2])
    report("FC06 echo response", ok)
    resp = req(ser, 0x03, bytes([0x00, 0x05, 0x00, 0x01]))
    v = (resp[2][1] << 8 | resp[2][2]) if resp and resp[1] == 0x03 else -1
    report("FC06 read-back = 0xABCD", v == 0xABCD, f"-> {hex(v)}")

    # ---- FC16 Write Multiple Registers ----
    print("[FC16] Write Multiple Registers 0x000A x3 = [0x1111,0x2222,0x3333]")
    vals = [0x1111, 0x2222, 0x3333]
    payload = bytes([0x00, 0x0A, 0x00, 0x03, 0x06])
    payload += b''.join(bytes([v >> 8, v & 0xFF]) for v in vals)
    resp = req(ser, 0x10, payload)
    ok = resp and resp[0] == SLAVE and resp[1] == 0x10 and resp[2][:6] == bytes([0x00, 0x0A, 0x00, 0x03]) and check_crc(resp[2])
    report("FC16 response (addr+cnt)", ok)
    resp = req(ser, 0x03, bytes([0x00, 0x0A, 0x00, 0x03]))
    rb = [resp[2][1 + i * 2] << 8 | resp[2][2 + i * 2] for i in range(3)] if resp and resp[1] == 0x03 else []
    report("FC16 read-back matches", rb == vals, f"-> {[hex(v) for v in rb]}")

    # ---- Exception: write to out-of-range register ----
    print("[EXC] FC06 write to 0x00FF (out of range)")
    resp = req(ser, 0x06, bytes([0x00, 0xFF, 0x12, 0x34]))
    ok = resp and resp[0] == SLAVE and resp[1] == 0x86 and resp[2][0] == 0x02 and check_crc(resp[2])
    report("EXC code=02 (illegal data address)", ok)

    # ---- Exception: illegal function code ----
    print("[EXC] FC 0x99 (unsupported)")
    resp = req(ser, 0x99, b'\x00\x00\x00\x00\x00\x00')
    ok = resp and resp[0] == SLAVE and resp[1] == 0x99 and resp[2][0] == 0x01 and check_crc(resp[2])
    report("EXC code=01 (illegal function)", ok)

    # ---- Exception: read count out of range ----
    print("[EXC] FC03 count=0 (illegal)")
    resp = req(ser, 0x03, bytes([0x00, 0x00, 0x00, 0x00]))
    ok = resp and resp[0] == SLAVE and resp[1] == 0x83 and resp[2][0] == 0x02 and check_crc(resp[2])
    report("EXC code=02 on count=0", ok)

    ser.close()
    print(f"\n=== RESULT: {PASS} passed, {FAIL} failed ===")
    sys.exit(1 if FAIL else 0)


if __name__ == '__main__':
    main()
