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

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from firmforge.infrastructure import paths

WORKSPACE = Path(__file__).resolve().parent.parent
EXAMPLES_BASE = paths.examples_dir() / "arduino"

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
    # 每个用例前清掉运行时指纹。benchmark 要的是「每例真编一次」，而
    # .ff-run/state.json 是跨例共享的：实测不清会串味，出现一批
    # 「rc!=0 且 stdout/stderr 全空」的假失败（2026-10-23 排查了一轮）。
    (WORKSPACE / ".ff-run" / "state.json").unlink(missing_ok=True)
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
            combined = (r.stdout or "") + "\n" + (r.stderr or "")
            for line in combined.splitlines():
                low = line.lower()
                if "fatal error" in low or "error:" in low:
                    error = line.strip()
                    break
            if not error:
                tail = [ln.strip() for ln in combined.splitlines() if ln.strip()]
                error = tail[-1][:160] if tail else f"rc={r.returncode}，子进程无任何输出"
        return {"build_pass": success, "build_elapsed_ms": elapsed,
                "build_rc": r.returncode, "build_error": error}
    except subprocess.TimeoutExpired:
        return {"build_pass": False, "build_elapsed_ms": 120_000,
                "build_rc": None, "build_error": "TIMEOUT"}
    except Exception as e:
        return {"build_pass": False, "build_elapsed_ms": 0,
                "build_rc": None, "build_error": str(e)}


def run_flash(example_path: Path, expected: str, board: str) -> dict:
    """Run ff verify with expected serial pattern."""
    t0 = time.time()
    cmd = [sys.executable, "-m", "firmforge", "run", board,
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


def run_build_batch(pairs, board):
    """一次子进程构建多个用例。

    pairs: [(rel, Path), ...]
    返回 {rel: build_result}

    为什么要有这条：这台机器起一个 Python 进程要 ~1.9 s（实测，真正导入
    firmforge 只占 0.25 s），73 个用例光启动就 2.3 分钟。`ff build --apps`
    把进程启动收成一次，编译仍是一例一次，语义不变。
    """
    import tempfile

    tmp = Path(tempfile.gettempdir()) / "ff_bench_apps.txt"
    tmp.write_text("\n".join(str(p) for _, p in pairs), encoding="utf-8")

    r = subprocess.run(
        # --json 是全局参数，必须放在子命令之前
        [sys.executable, "-m", "firmforge", "--json", "build", board,
         "--apps", f"@{tmp}"],
        capture_output=True, text=True, timeout=1800, cwd=str(WORKSPACE),
    )

    try:
        payload = json.loads(r.stdout.strip() or "{}")
    except json.JSONDecodeError:
        payload = {}

    def _key(s: str) -> str:
        return str(s).replace("\\", "/").rstrip("/").lower()

    by_app = {_key(x.get("app", "")): x for x in payload.get("results", [])}
    out: dict[str, dict] = {}
    for rel, p in pairs:
        x = by_app.get(_key(p))
        if x is None:
            tail = (r.stderr or "").strip().splitlines()[-1:] or [""]
            out[rel] = {
                "build_pass": False, "build_elapsed_ms": 0, "build_rc": r.returncode,
                "build_error": f"批量结果中缺少该用例（批次 rc={r.returncode}，stderr 尾：{tail[0][:120]!r}）",
            }
        else:
            out[rel] = {
                "build_pass": bool(x.get("pass")),
                "build_elapsed_ms": x.get("elapsed_ms", 0),
                "build_rc": None,
                "build_error": x.get("error", ""),
            }
    return out


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--category", "-c", help="Single category, e.g. 01.Basics")
    ap.add_argument("--flash", action="store_true", help="Also run flash+test")
    ap.add_argument("--board", "-b", default="arduino_mega", help="Board ID (default: arduino_mega)")
    ap.add_argument("--no-batch", action="store_true",
                    help="每例单独起一个 ff 进程（默认走 ff build --apps 批量，省掉进程启动开销）")
    ap.add_argument("--limit", type=int, default=0,
                    help="本次最多跑几个用例（0=不限）。用于把长跑切片：环境对单轮"
                         "文件删除量有上限，一次跑完 70+ 例会被拦。")
    args = ap.parse_args()

    board = args.board
    results_file = _results_file(board)
    data = load_results(results_file)
    existing = {r["example"] for r in data.get("results", [])}

    if args.category:
        categories = [args.category]
    else:
        categories = CATEGORIES["builtin"] + CATEGORIES["avr"]

    # flash 必须逐例（每个用例的输出断言不同），所以只有纯构建才走批量
    use_batch = not args.no_batch and not args.flash
    budget = args.limit or 0   # 0 = 不限

    for cat in categories:
        examples = find_examples(cat)
        if not examples:
            print(f"[{cat}] NOT FOUND")
            continue
        print(f"\n[{cat}] {len(examples)} examples")

        todo = []
        for ep in examples:
            rel = str(ep.relative_to(EXAMPLES_BASE))
            if rel in existing:
                print(f"  SKIP {rel} (already tested)")
            else:
                todo.append((rel, ep))
        if not todo:
            continue

        if budget:
            if budget <= 0:
                print("  (--limit 用尽，停止)")
                continue
            if len(todo) > budget:
                print(f"  (--limit {budget}：本次只跑前 {budget} 个，其余下次继续)")
                todo = todo[:budget]
            budget -= len(todo)

        if use_batch:
            t0 = time.time()
            batch = run_build_batch(todo, board)
            wall = (time.time() - t0) * 1000
            print(f"  (batch: {len(todo)} examples, wall {wall:.0f}ms)")
            for rel, ep in todo:
                br = batch[rel]
                entry = {"example": rel, "category": cat, **br}
                status = "PASS" if br["build_pass"] else "FAIL"
                print(f"  {status} {rel} ({br['build_elapsed_ms']:.0f}ms)")
                if br.get("build_error"):
                    print(f"    -> {br['build_error'][:120]}")
                data.setdefault("results", []).append(entry)
            save_results(results_file, data)
            continue

        for rel, ep in todo:
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
