import sys
sys.path.insert(0, r"C://MyLab//MCU")
import json, time, urllib.request

BASE = "http://127.0.0.1:9878/modbus"
passed, failed = 0, 0

def mb(mb_dict):
    req = urllib.request.Request(BASE, data=json.dumps({"mb": mb_dict}).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=8) as r:
        return json.loads(r.read().decode())

def compact(s): return s.replace(" ", "").upper()
def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1; print(f"  PASS  {name}")
    else:
        failed += 1; print(f"  FAIL  {name}  {detail}")

print("=== A. 合法帧（HTTP /modbus） ===")
r = mb({"slave":1,"fc":3,"addr":0,"count":1})
check("FC03 reg0=0x1234(固定标志)", r["ok"] and "1234" in compact(r["raw"]), r["raw"])
r = mb({"slave":1,"fc":3,"addr":0,"count":5})
h = compact(r["raw"])
check("FC03 5regs 1234,1001-1004", r["ok"] and all(x in h for x in ["1234","03E9","03EA","03EB","03EC"]), r["raw"])
r = mb({"slave":1,"fc":4,"addr":0,"count":3})
h = compact(r["raw"])
check("FC04 3regs 2000-2002", r["ok"] and all(x in h for x in ["07D0","07D1","07D2"]), r["raw"])
r = mb({"slave":1,"fc":6,"addr":5,"count":0,"data":"43981"})
check("FC06 write 0xABCD echo", r["ok"] and "ABCD" in compact(r["raw"]), r["raw"])
r = mb({"slave":1,"fc":3,"addr":5,"count":1})
check("FC06 readback reg5=0xABCD", "ABCD" in compact(r["raw"]), r["raw"])
r = mb({"slave":1,"fc":16,"addr":10,"count":3,"data":"11,22,33"})
check("FC16 write echo count=3", r["ok"] and "0003" in compact(r["raw"]), r["raw"])
r = mb({"slave":1,"fc":3,"addr":10,"count":3})
h = compact(r["raw"])
check("FC16 readback 11,22,33", all(x in h for x in ["000B","0016","0021"]), r["raw"])
r = mb({"slave":1,"fc":3,"addr":99,"count":5})
check("异常: 越界 FC03 -> 0x83 0x02", "8302" in compact(r["raw"]), r["raw"])
r = mb({"slave":1,"fc":3,"addr":0,"count":0})
check("异常: count=0 -> 0x83 0x02", "8302" in compact(r["raw"]), r["raw"])
r = mb({"slave":1,"fc":3,"addr":0,"count":21})
check("异常: count超限 -> 0x83 0x02", "8302" in compact(r["raw"]), r["raw"])
r = mb({"slave":2,"fc":3,"addr":0,"count":1})
check("非法slave: 无响应", "(no response)" in r["raw"], r["raw"])

print("=== B. 非法帧直发（pyserial） ===")
urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:9878/serial-close", method="POST")).read()
import serial
from firmforge.tools.modbus_utils import modbus_crc
ser = None
for _ in range(20):  # wait for collector to release COM5
    try:
        ser = serial.Serial("COM5", 9600, timeout=1); break
    except Exception:
        time.sleep(0.5)
check("COM5 释放可打开", ser is not None)
if ser:
    time.sleep(2); ser.reset_input_buffer()  # pyserial open resets Mega; wait for boot
    fc43 = bytes.fromhex("01 2B 00 00 00 01") + modbus_crc(bytes.fromhex("01 2B 00 00 00 01")).to_bytes(2,"little")
    ser.write(fc43); time.sleep(0.2)
    r1 = ser.read(20)
    check("FC43 非法功能码 -> 0xAB 0x01", "AB01" in r1.hex().upper(), r1.hex())
    pdu = bytes.fromhex("01 10 00 00 00 02 02 00 01 00 02")  # count=2 bc=2 (应6)
    bad16 = pdu + modbus_crc(pdu).to_bytes(2,"little")
    ser.write(bad16); time.sleep(0.2)
    r2 = ser.read(20)
    check("FC16 bc不匹配 -> 0x90 0x02", "9002" in r2.hex().upper(), r2.hex())
    pdu6 = bytes.fromhex("01 06 00 64 12 34")  # addr 100 (越界)
    bad6 = pdu6 + modbus_crc(pdu6).to_bytes(2,"little")
    ser.write(bad6); time.sleep(0.2)
    r3 = ser.read(20)
    check("FC06 越界 addr100 -> 0x86 0x02", "8602" in r3.hex().upper(), r3.hex())
    pdu16o = bytes.fromhex("01 10 00 64 00 01 02 00 2A")  # FC16 addr100 (越界)
    bad16o = pdu16o + modbus_crc(pdu16o).to_bytes(2,"little")
    ser.write(bad16o); time.sleep(0.2)
    r4 = ser.read(20)
    check("FC16 越界 addr100 -> 0x90 0x02", "9002" in r4.hex().upper(), r4.hex())
    ser.close()
urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:9878/serial-open", method="POST")).read()

print(f"\n=== RESULT: {passed} passed, {failed} failed ===")
