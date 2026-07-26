"""
Benchmark runner: tests official Arduino examples on Mega2560.

Usage:
    python scripts/benchmark_runner.py                              # all examples
    python scripts/benchmark_runner.py --category 01.Basics         # single category
    python scripts/benchmark_runner.py --board arduino_328p         # UNO board

Records results to docs/test_benchmark/official_examples_{board}_{date}.json
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent.parent
EXAMPLES_BASE = Path.home() / ".firmforge" / "examples" / "arduino"

def _results_file(board: str) -> Path:
    date = time.strftime("%Y%m%d")
    return WORKSPACE / "docs" / "test_benchmark" / f"official_examples_{board}_{date}.json"

# ── categories ─────────────────────────────────────────────────────────────

CATEGORIES = {
    "builtin": [
        "01.Basics", "02.Digital", "03.Analog", "04.Communication",
        "05.Control", "08.Strings", "09.USB",
    ],
    "avr": ["EEPROM", "SoftwareSerial", "SPI", "Wire"],
}

SERIAL_PATTERNS = {
    "AnalogReadSerial": "sensor",
    "DigitalReadSerial": "sensor",
    "ReadAnalogVoltage": "voltage",
    "ASCIITable": "hex",
    "SerialEvent": "READY",
    "ReadASCIIString": r"\d+",
    "SerialCallResponse": "Ready",
    "SerialCallResponseASCII": "Ready",
    "MultiSerial": "Hello",
    "Fade": "",
    "Switch": "",
}


def load_results(results_file: Path) -> dict:
    if results_file.exists():
        return json.loads(results_file.read_text(encoding="utf-8"))
    return {"board": "", "tested_at": "", "results": []}


def save_results(results_file: Path, data: dict):
    data["tested_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    results_file.parent.mkdir(exist_ok=True)
    results_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def find_examples(category: str) -> list[Path]:
    """Find all .ino directories in a category."""
    base = EXAMPLES_BASE
    cat_dir = base / "builtin" / category
    if not cat_dir.exists():
        cat_dir = base / "avr" / category
    if not cat_dir.exists():
        return []

    examples = []
    for sub in sorted(cat_dir.iterdir()):
        if sub.is_dir():
            inos = list(sub.glob("*.ino"))
            if inos:
                examples.append(sub)
    return examples


def run_build(example_path: Path, board: str) -> dict:
    """Run ff build and return result."""
    t0 = time.time()
    try:
        r = subprocess.run(
            [sys.executable, "-m", "firmforge", "build", board,
             "--app", str(example_path)],
            capture_output=True, text=True, timeout=120, cwd=str(WORKSPACE),
        )
        elapsed = (time.time() - t0) * 1000
        success = "BUILD PASSED" in r.stdout or "S3 Build: PASS" in (r.stderr + r.stdout)
        error = ""
        if not success:
            for line in (r.stderr + r.stdout).splitlines():
                if "error" in line.lower() or "Error" in line:
                    error = line.strip()
                    break
        return {"build_pass": success, "build_elapsed_ms": elapsed, "build_error": error}
    except subprocess.TimeoutExpired:
        return {"build_pass": False, "build_elapsed_ms": 120_000, "build_error": "TIMEOUT"}
    except Exception as e:
        return {"build_pass": False, "build_elapsed_ms": 0, "build_error": str(e)}


def run_flash(example_path: Path, expected: str, board: str) -> dict:
    """Run ff verify with expected serial pattern."""
    t0 = time.time()
    cmd = [sys.executable, "-m", "firmforge", "verify", board,
           "--app", str(example_path)]
    if expected:
        cmd.extend(["--expected", expected])

    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120, cwd=str(WORKSPACE))
        elapsed = (time.time() - t0) * 1000
        success = "ALL STAGES PASSED" in r.stdout
        return {"flash_pass": success, "flash_elapsed_ms": elapsed}
    except subprocess.TimeoutExpired:
        return {"flash_pass": False, "flash_elapsed_ms": 120_000, "flash_error": "TIMEOUT"}
    except Exception as e:
        return {"flash_pass": False, "flash_elapsed_ms": 0, "flash_error": str(e)}


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--category", "-c", help="Single category, e.g. 01.Basics")
    ap.add_argument("--flash", action="store_true", help="Also run flash+test")
    ap.add_argument("--board", "-b", default="arduino_mega", help="Board ID (default: arduino_mega)")
    args = ap.parse_args()

    board = args.board
    results_file = _results_file(board)
    data = load_results(results_file)
    existing = {r["example"] for r in data.get("results", [])}

    if args.category:
        categories = [args.category]
    else:
        categories = CATEGORIES["builtin"] + CATEGORIES["avr"]

    for cat in categories:
        examples = find_examples(cat)
        if not examples:
            print(f"[{cat}] NOT FOUND")
            continue
        print(f"\n[{cat}] {len(examples)} examples")

        for ep in examples:
            rel = str(ep.relative_to(EXAMPLES_BASE))
            if rel in existing:
                print(f"  SKIP {rel} (already tested)")
                continue

            # Phase 1: build
            br = run_build(ep, board)
            name = ep.name

            entry = {
                "example": rel,
                "category": cat,
                **br,
            }

            # Phase 2: flash (if requested, and build passed)
            if args.flash and br["build_pass"] and name in SERIAL_PATTERNS:
                fr = run_flash(ep, SERIAL_PATTERNS[name], board)
                entry.update(fr)
            elif args.flash and br["build_pass"]:
                fr = run_flash(ep, "", board)
                entry.update(fr)

            status = "PASS" if br["build_pass"] else "FAIL"
            flash_info = ""
            if "flash_pass" in entry:
                flash_info = f" flash={'OK' if entry['flash_pass'] else 'FAIL'}"

            print(f"  {status} {rel} ({br['build_elapsed_ms']:.0f}ms{flash_info})")
            if br.get("build_error"):
                print(f"    -> {br['build_error'][:120]}")

            data.setdefault("results", []).append(entry)
            save_results(results_file, data)

    # Summary
    total = len(data.get("results", []))
    passed = sum(1 for r in data.get("results", []) if r["build_pass"])
    flashed = sum(1 for r in data.get("results", []) if r.get("flash_pass"))
    print(f"\n=== [{board}] SUMMARY: {passed}/{total} build passed, {flashed} flash passed ===")
    print(f"Results: {results_file}")


if __name__ == "__main__":
    main()
