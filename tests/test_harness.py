#!/usr/bin/env python3
"""Simple benchmark runner - uses pre-existing test code on disk."""
import subprocess, json, time
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent
PYTHON = r"C:\Program Files\Python312\python.exe"
RESULT_FILE = ROOT / "docs" / "test_benchmark" / "results.json"
REG_DIR = ROOT / "boards" / "arduino_mega" / "apps" / "test_reg"
INO_DIR = ROOT / "boards" / "arduino_mega" / "apps" / "test_ino"

def run_verify(app_dir):
    t0 = time.time()
    state = ROOT / ".firmforge" / "state.json"
    if state.exists(): state.write_text("{}")
    try:
        r = subprocess.run([PYTHON, "-m", "firmforge", "verify", "arduino_mega", "--app", app_dir],
                           capture_output=True, text=True, timeout=60, cwd=str(ROOT))
    except Exception as e:
        return {"error": str(e), "all_pass": False, "elapsed_ms": int((time.time()-t0)*1000)}
    out = r.stdout + r.stderr
    errors = [l.strip() for l in out.splitlines() if "error:" in l.lower() and len(l) < 200]
    return {"all_pass": "ALL STAGES PASSED" in out, "elapsed_ms": int((time.time()-t0)*1000),
            "errors": errors[:5], "review_pass": "S2 Review: PASS" in out,
            "build_pass": "S3 Build: PASS" in out, "flash_pass": "S4 Flash: PASS" in out}

def scan_apps(base_dir):
    apps = []
    for d in sorted(base_dir.iterdir()):
        if d.is_dir() and d.name.startswith('R'):
            apps.append(d)
    return apps

def main():
    reqs = json.loads((ROOT / "docs/test_benchmark/NL_REQUIREMENTS.json").read_text(encoding="utf-8"))["requirements"]
    rid_to_cat = {r["id"]: r["category"] for r in reqs}
    
    reg_apps = scan_apps(REG_DIR)
    ino_apps = scan_apps(INO_DIR)
    
    results = []
    total = len(reg_apps) + len(ino_apps)
    
    for paradigm, apps in [("reg", reg_apps), ("ino", ino_apps)]:
        for app_dir in apps:
            rid = app_dir.name[1:]  # remove 'R' prefix
            cat = rid_to_cat.get(rid, "unknown")
            
            v = run_verify(str(app_dir))
            r = {"id": rid, "paradigm": paradigm, "category": cat, **v,
                 "timestamp": datetime.now().isoformat()}
            results.append(r)
            
            # Save incrementally
            RESULT_FILE.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
            
            status = "PASS" if v["all_pass"] else "FAIL"
            errors = "; ".join(v.get("errors", ["-"])[:2])
            print(f"[{len(results):3d}/{total}] R{rid} {paradigm:3s} {cat:8s} {status} [{v['elapsed_ms']}ms]")
            if not v["all_pass"] and v.get("errors"):
                print(f"       {errors[:100]}")
            
            time.sleep(2)
    
    reg_p = sum(1 for r in results if r["paradigm"]=="reg" and r["all_pass"])
    ino_p = sum(1 for r in results if r["paradigm"]=="ino" and r["all_pass"])
    print(f"\nDONE. Register: {reg_p}/{len(reg_apps)}  Arduino: {ino_p}/{len(ino_apps)}  Total: {reg_p+ino_p}/{total}")

if __name__ == "__main__":
    main()
