#!/usr/bin/env python3
"""Re-run Arduino examples benchmark with bugfixes applied."""
import subprocess, json, time, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYTHON = sys.executable
EXAMPLES_DIR = ROOT / "boards" / "arduino_328p" / "apps" / "examples_ino"
RESULT_FILE = ROOT / "docs" / "test_benchmark" / "examples_results.json"
BOARD = "arduino_328p"

def run_verify(app_dir):
    t0 = time.time()
    state = ROOT / ".firmforge" / "state.json"
    if state.exists(): state.write_text("{}")
    try:
        r = subprocess.run(
            [PYTHON, "-m", "firmforge", "verify", BOARD, "--app", str(app_dir)],
            capture_output=True, text=True, timeout=60, cwd=str(ROOT),
        )
    except Exception as e:
        return {"all_pass": False, "ms": int((time.time()-t0)*1000), "errors": [str(e)]}
    out = r.stdout + r.stderr
    errors = [l.strip() for l in out.splitlines() if "error:" in l.lower() and len(l) < 200]
    return {"all_pass": "ALL STAGES PASSED" in out, "ms": int((time.time()-t0)*1000),
            "errors": errors[:3]}

def main():
    apps = sorted([d for d in EXAMPLES_DIR.iterdir() if d.is_dir()])
    results = []
    
    for i, app_dir in enumerate(apps):
        name = app_dir.name
        v = run_verify(str(app_dir))
        r = {"name": name, "all_pass": v["all_pass"], "ms": v["ms"], "errors": v["errors"]}
        results.append(r)
        
        status = "PASS" if v["all_pass"] else "FAIL"
        errs = "; ".join(v.get("errors", ["-"])[:1])[:60]
        print(f"[{i+1:3d}/{len(apps)}] {name[:45]:45s} {status} [{v['ms']}ms] {errs}")
    
    RESULT_FILE.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    
    passes = sum(1 for r in results if r["all_pass"])
    print(f"\nDONE. {passes}/{len(apps)} passed ({(passes/len(apps)*100):.1f}%)")

if __name__ == "__main__":
    main()
