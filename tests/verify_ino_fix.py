#!/usr/bin/env python3
"""Quick verification of .ino fix: run a few previously-failing examples."""
import subprocess, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYTHON = r"C:\Users\radar\.workbuddy\binaries\python\versions\3.13.12\python.exe"
BOARD = "arduino_328p"

# Previously-failing examples (ino prototype issues, not missing libs)
targets = [
    "04_Communication_Dimmer",
    "05_Control_WhileStatementConditional",
    "04_Communication_SerialCallResponse",
    "04_Communication_SerialCallResponseASCII",
    "04_Communication_Midi",
    "04_Communication_PhysicalPixel",
    "04_Communication_SerialEvent",
    "04_Communication_VirtualColorMixer",
    "07_Display_RowColumnScanning",
    "lib_Wire_slave_sender",
    "lib_Wire_slave_receiver",
    "lib_Wire_SFRRanger_reader",
]

base = ROOT / "boards" / "arduino_328p" / "apps" / "examples_ino"
passed = 0
failed = 0

for name in targets:
    app_dir = base / name
    if not app_dir.is_dir():
        print(f"[SKIP] {name} — not found")
        continue
    
    state = ROOT / ".firmforge" / "state.json"
    if state.exists(): state.write_text("{}")
    
    t0 = time.time()
    r = subprocess.run(
        [PYTHON, "-m", "firmforge", "run", BOARD, "--app", str(app_dir)],
        capture_output=True, text=True, timeout=120, cwd=str(ROOT),
    )
    ms = int((time.time()-t0)*1000)
    ok = "ALL STAGES PASSED" in (r.stdout + r.stderr)
    
    if ok:
        passed += 1
        print(f"[PASS] {name:40s} {ms}ms")
    else:
        failed += 1
        errs = [l.strip() for l in (r.stdout+r.stderr).splitlines() if "error:" in l.lower()]
        err = (errs[0][:80] if errs else "?")[:80]
        print(f"[FAIL] {name:40s} {ms}ms  {err}")

print(f"\n{passed}/{passed+failed} passed")
