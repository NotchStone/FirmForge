"""NL Requirements automated test runner for Mega2560."""
from pathlib import Path
import subprocess, sys, json, time

WORKSPACE = Path(__file__).resolve().parent.parent
STATE = WORKSPACE / ".firmforge" / "state.json"
RESULTS = WORKSPACE / "docs" / "test_benchmark" / f"nl_results_mega2560_{time.strftime('%Y%m%d')}.json"
TEST_DIR = WORKSPACE / "boards" / "arduino_mega" / "nl_tests"

def clear(): STATE.write_text('{}')

def verify(req_id: str) -> dict:
    clear()
    t0 = time.time()
    r = subprocess.run([sys.executable, "-m", "firmforge", "verify", "arduino_mega",
                        "--app", str(TEST_DIR / req_id)],
                       capture_output=True, text=True, timeout=120, cwd=str(WORKSPACE))
    elapsed = (time.time() - t0) * 1000
    return {
        "id": req_id,
        "passed": "ALL STAGES PASSED" in r.stdout,
        "build_pass": "S3 Build: PASS" in (r.stderr + r.stdout),
        "flash_pass": "S4 Flash: PASS" in (r.stderr + r.stdout),
        "elapsed_ms": elapsed,
        "stdout": r.stdout[-200:] if "ALL STAGES PASSED" not in r.stdout else ""
    }

def load():
    if RESULTS.exists():
        return json.loads(RESULTS.read_text(encoding="utf-8"))
    return []

def save(entries):
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("req_ids", nargs="+", help="e.g. R11 R12 R13")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    results = load()
    done = {r["id"] for r in results}

    for rid in args.req_ids:
        if rid in done:
            print(f"SKIP {rid} (already tested)")
            continue
        entry = verify(rid)
        status = "PASS" if entry["passed"] else "FAIL"
        print(f"{status} {rid} ({entry['elapsed_ms']:.0f}ms)")
        results.append(entry)
        save(results)
