"""
Batch verification of Arduino official examples on Mega2560.

Runs ff build on all selected examples, ff verify (with flash) on
serial-output examples, and records failures to ExperienceLedger.
"""

import json
import os
import sys
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from firmforge.core.pipeline_runner import PipelineRunner
from firmforge.core.experience_ledger import ExperienceLedger

# ── Configuration ──────────────────────────────────────────────────────────

BOARD_ID = "arduino_mega"
EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "vendor" / "arduino" / "examples"
WORKSPACE = Path(__file__).resolve().parent.parent
LEDGER_PATH = WORKSPACE / ".firmforge" / "ledger.jsonl"

# Examples that produce serial output — can be build+flash+test
SERIAL_EXAMPLES = [
    "01_Basics_AnalogReadSerial",
    "01_Basics_DigitalReadSerial",
    "01_Basics_ReadAnalogVoltage",
    "04_Communication_ASCIITable",
    "08_Strings_CharacterAnalysis",
    "08_Strings_StringAdditionOperator",
]

# Full set for build-only — no hardware dependencies
BUILD_ONLY_EXAMPLES = [
    "01_Basics_Blink",
    "01_Basics_BareMinimum",
    "01_Basics_Fade",
    "02_Digital_BlinkWithoutDelay",
    "02_Digital_toneMelody",
    "02_Digital_tonePitchFollower",
    "03_Analog_AnalogWriteMega",
    "05_Control_Arrays",
    "05_Control_ForLoopIteration",
    "08_Strings_StringLength",
    "09_USB_KeyboardLogout",  # compile-only, no USB hardware
]

# ── Helpers ─────────────────────────────────────────────────────────────────

ledger = ExperienceLedger(LEDGER_PATH)


def run_build(example_name: str) -> dict:
    """Run ff build on a single example. Returns result dict."""
    app_dir = EXAMPLES_DIR / example_name
    if not app_dir.exists():
        return {"example": example_name, "status": "SKIP", "reason": f"Not found: {app_dir}"}

    t0 = time.time()
    try:
        runner = PipelineRunner(workspace=WORKSPACE, leder_path=str(LEDGER_PATH))
        result = runner.run_build(BOARD_ID, str(app_dir))
        elapsed = (time.time() - t0) * 1000
        return {
            "example": example_name,
            "status": "PASS" if result.overall_success else "FAIL",
            "elapsed_ms": elapsed,
            "build_elapsed": result.stages[2].elapsed_ms if len(result.stages) > 2 else 0,
            "error": result.stages[2].error if len(result.stages) > 2 and not result.overall_success else None,
        }
    except Exception as e:
        elapsed = (time.time() - t0) * 1000
        return {"example": example_name, "status": "ERROR", "elapsed_ms": elapsed, "error": str(e)}


def run_verify(example_name: str, expected_pattern: str = ".") -> dict:
    """Run ff verify (build + flash + test) on a single example."""
    app_dir = EXAMPLES_DIR / example_name
    if not app_dir.exists():
        return {"example": example_name, "status": "SKIP", "reason": f"Not found: {app_dir}"}

    t0 = time.time()
    try:
        runner = PipelineRunner(workspace=WORKSPACE, leder_path=str(LEDGER_PATH))
        result = runner.run_full(BOARD_ID, str(app_dir), expected=expected_pattern)
        elapsed = (time.time() - t0) * 1000
        stages_ok = all(s.success for s in result.stages)
        return {
            "example": example_name,
            "status": "PASS" if stages_ok else "FAIL",
            "elapsed_ms": elapsed,
            "stages": {s.name: {"success": s.success, "elapsed_ms": s.elapsed_ms}
                        for s in result.stages},
        }
    except Exception as e:
        elapsed = (time.time() - t0) * 1000
        return {"example": example_name, "status": "ERROR", "elapsed_ms": elapsed, "error": str(e)}


def record_failure(example: str, stage: str, error: str):
    """Log a build/flash failure to the experience ledger."""
    ledger.record(
        mcu_platform="avr",
        mcu_chip="ATmega2560",
        source_context=example,
        error_keyword=error[:120] if error else "unknown",
        fix_description=f"Batch test: {example} failed at {stage}",
        resolution_success=False,
    )


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    print(f"{'='*60}")
    print(f"FirmForge Batch Verification — {BOARD_ID}")
    print(f"Examples dir: {EXAMPLES_DIR}")
    print(f"{'='*60}\n")

    results = []
    build_total = 0
    build_pass = 0

    # ── Phase 1: Build-only ─────────────────────────────────────────────────
    print("[Phase 1] Build-only examples\n")
    for name in BUILD_ONLY_EXAMPLES:
        r = run_build(name)
        results.append(r)
        build_total += 1
        if r["status"] == "PASS":
            build_pass += 1
            print(f"  BUILD PASS  {name} ({r['elapsed_ms']:.0f}ms)")
        else:
            print(f"  BUILD FAIL  {name}  —  {r.get('error', '?')}")
            record_failure(name, "build", str(r.get("error", "")))

    # ── Phase 2: Build+Flash+Test ───────────────────────────────────────────
    print(f"\n[Phase 2] Build+Flash+Test examples\n")
    flash_total = 0
    flash_pass = 0
    for name in SERIAL_EXAMPLES:
        # Clear state to force full pipeline
        state_file = WORKSPACE / ".firmforge" / "state.json"
        if state_file.exists():
            state_file.unlink()

        r = run_verify(name, expected_pattern=".")
        results.append(r)
        flash_total += 1
        if r["status"] == "PASS":
            flash_pass += 1
            print(f"  FULL PASS   {name} ({r['elapsed_ms']:.0f}ms)")
        else:
            # Check which stage failed
            stages_info = r.get("stages", {})
            failed_stages = [s for s, v in stages_info.items() if not v["success"]]
            print(f"  FULL FAIL   {name}  —  failed: {failed_stages}")
            record_failure(name, "run", str(r))

    # ── Summary ─────────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"RESULTS")
    print(f"  Build:  {build_pass}/{build_total} passed")
    print(f"  Flash:  {flash_pass}/{flash_total} passed")
    print(f"  Total:  {build_pass + flash_pass}/{build_total + flash_total} passed")
    print(f"{'='*60}")

    # Save results JSON
    report_path = WORKSPACE / ".firmforge" / "batch_results.json"
    report = {
        "board": BOARD_ID,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "build": {"total": build_total, "passed": build_pass},
        "flash": {"total": flash_total, "passed": flash_pass},
        "results": results,
    }
    report_path.parent.mkdir(exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"\nReport saved → {report_path}")

    # List ledger entries
    ledger_entries = list(ledger.search(limit=50))
    if ledger_entries:
        print(f"\nLedger entries: {len(leder_entries)}")
        for entry in ledger_entries[-10:]:
            print(f"  [{entry.severity}] {entry.source_context}: {entry.error_keyword}")


if __name__ == "__main__":
    main()
