#!/usr/bin/env python3
"""Arduino Official Examples Benchmark — 85 examples on UNO."""
import subprocess, json, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYTHON = r"C:\Program Files\Python312\python.exe"
EXAMPLES_DIR = ROOT / "boards" / "arduino_uno" / "apps" / "examples_ino"
RESULT_FILE = ROOT / "docs" / "test_benchmark" / "examples_results.json"
BOARD = "arduino_328p"

def run_verify(app_dir):
    t0 = time.time()
    state = ROOT / ".firmforge" / "state.json"
    if state.exists(): state.write_text("{}")
    try:
        r = subprocess.run([PYTHON, "-m", "firmforge", "verify", BOARD, "--app", str(app_dir)],
                           capture_output=True, text=True, timeout=60, cwd=str(ROOT))
    except Exception as e:
        return {"all_pass": False, "error": str(e), "ms": int((time.time()-t0)*1000)}
    out = r.stdout + r.stderr
    errors = [l.strip() for l in out.splitlines() if "error:" in l.lower() and len(l) < 200]
    return {"all_pass": "ALL STAGES PASSED" in out, "ms": int((time.time()-t0)*1000),
            "errors": errors[:3]}

def load_results():
    if RESULT_FILE.exists():
        return json.loads(RESULT_FILE.read_text(encoding="utf-8"))
    return []

def save_results(results):
    RESULT_FILE.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

def main():
    results = load_results()
    done = {r["name"] for r in results}
    apps = sorted([d for d in EXAMPLES_DIR.iterdir() if d.is_dir()])
    
    for app_dir in apps:
        name = app_dir.name
        if name in done:
            continue
        
        v = run_verify(str(app_dir))
        r = {"name": name, "all_pass": v["all_pass"], "ms": v["ms"], "errors": v["errors"]}
        results.append(r)
        save_results(results)
        
        status = "PASS" if v["all_pass"] else "FAIL"
        n = len(results)
        errs = "; ".join(v.get("errors", ["-"])[:1])[:60]
        print(f"[{n:3d}/{len(apps)}] {name[:45]:45s} {status} [{v['ms']}ms] {errs}")
    
    passes = sum(1 for r in results if r["all_pass"])
    print(f"\nDONE. {passes}/{len(apps)} passed")

if __name__ == "__main__":
    main()
