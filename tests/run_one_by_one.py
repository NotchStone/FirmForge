#!/usr/bin/env python3
"""One-at-a-time benchmark — see Agent feedback loop in action."""
import subprocess, json, time, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYTHON = r"C:\Program Files\Python312\python.exe"

def run_one(rid, paradigm):
    d = ROOT / "boards" / "arduino_mega" / "apps" / f"test_{paradigm}" / f"R{rid}"
    if not d.is_dir():
        return None
    
    state = ROOT / ".firmforge" / "state.json"
    if state.exists(): state.write_text("{}")
    
    t0 = time.time()
    r = subprocess.run([PYTHON, "-m", "firmforge", "run", "arduino_mega", "--app", str(d)],
                       capture_output=True, text=True, timeout=60, cwd=str(ROOT))
    out = r.stdout + r.stderr
    elapsed = int((time.time()-t0)*1000)
    all_pass = "ALL STAGES PASSED" in out
    
    # Extract errors
    errors = []
    for line in out.splitlines():
        if "error:" in line.lower() and len(line) < 200:
            errors.append(line.strip()[:120])
    
    # Extract review info
    review = ""
    for line in out.splitlines():
        if "Source review:" in line:
            review = line.split("Source review:")[1].strip()[:50]
    
    return {"rid": rid, "par": paradigm, "pass": all_pass, "ms": elapsed,
            "review": review, "errors": errors[:3]}

# Process R01-R50
total = 0
passed = 0
for rid in [f"{i:02d}" for i in range(1, 51)]:
    for par in ["reg", "ino"]:
        total += 1
        r = run_one(rid, par)
        if r is None:
            continue
        
        status = "PASS" if r["pass"] else "FAIL"
        passed += 1 if r["pass"] else 0
        
        info = f"[{total:3d}/100] R{rid} {par:3s} {status} [{r['ms']}ms] {r['review']}"
        print(info)
        
        if not r["pass"] and r["errors"]:
            for e in r["errors"][:2]:
                print(f"  ↳ {e[:100]}")
        
        # Brief delay between tests
        if total < 100:
            time.sleep(2)

print(f"\n{'='*50}")
print(f"DONE. {passed}/{total} ALL STAGES PASSED")
