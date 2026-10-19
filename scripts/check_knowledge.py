"""Validate knowledge-base JSON files against their declared schemas.

每个知识库数据文件通过 `$schema` 声明自己的合约。本脚本解析该指针、用
jsonschema 做结构校验，并补上 JSON Schema 表达不了的**跨文件语义检查**：

  1. `pins.json` 的 `board` 必须存在于 `firmforge/data/boards/<board>/`
     —— 不一致不会报错，只会让 `get_pin_map(board_id)` 静默返回空
     （这正是 atmega328p 曾经的问题：board 写 arduino_uno，board_id 是
     arduino_328p）。
  2. 同一芯片目录下 registers.json 与 pins.json 的 `mcu` 必须一致。
  3. `registers.json` 内部同一地址不得被两个不同寄存器占用
     （16 位别名与其 L/H 视图除外）—— 见 `address_conflicts`。

为什么这个脚本重要：`knowledge_base.py` 用 `.get(...)` 宽松解析，格式写错
不抛异常、只静默返回空，进而让 S2 的寄存器审查全部变成漏检。silent
failure 是这个模块的默认失败模式，so 唯一可靠的拦截点就是这里。

Usage:
    python scripts/check_knowledge.py [--json]

Exit: 0 = 全部通过, 1 = 有失败, 2 = 运行环境缺依赖
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path


def find_repo_root(start: Path) -> Path:
    cur = start.resolve()
    for candidate in (cur, *cur.parents):
        if (candidate / ".git").exists():
            return candidate
    raise SystemExit("not inside a git work tree")


def _stm32_address_conflicts(payload: dict) -> list[str]:
    """STM32 的同址多寄存器：SVD 用「一地址多视图」表达模式相关寄存器。

    `TIMx.CCMR1_Output` / `CCMR1_Input`（同一寄存器的输出/输入两种解释）、
    `OTG_*_Host` / `OTG_*_Device`（主机/设备模式）都同址，这是 SVD 的
    合法写法，不是地址写错 —— 用 AVR 那套「16 位别名」判据会把它们
    全部报成冲突（首跑实测 12 条）。

    真正要报的是**同一外设内、名字只差编号**的同址条目：那意味着某个
    寄存器的偏移算错了（Flash 的 PRAR_PRG1 / PRAR_PRG2 相差 0x100，
    SVD 却写成同址）。生成器已按裁定表修正这类缺陷，这里是兜底。
    """
    out: list[str] = []
    for gname, group in payload.get("register_groups", {}).items():
        by_addr: dict[str, list[str]] = {}
        for reg in group.get("registers", []) or []:
            by_addr.setdefault(str(reg.get("address", "")), []).append(
                str(reg.get("name", "")))
        for addr, names in sorted(by_addr.items()):
            if len(names) < 2:
                continue
            stems: list[str] = []
            for name in names:
                num = re.search(r"(\d+)$", name)
                if num and len(num.group(1)) > 1 and num.group(1).startswith("0"):
                    # 前导零编号（SPDIFRX 的 `DR_00` / `DR_01` / `DR_10`）
                    # 是 SVD 的同址视图写法，不是「第 0/1 个」编号，
                    # 保留全名，不参与归并。
                    stems.append(name)
                else:
                    stems.append(re.sub(r"\d+$", "", name))
            if len(set(stems)) < len(set(names)):
                out.append(f"[{gname}] 地址 {addr} 上有名字仅差编号的寄存器: "
                           f"{', '.join(names)}")
    return out


def address_conflicts(payload: dict) -> list[str]:
    """同一地址被多个**不同**寄存器占用 —— 数据内部自相矛盾。

    按平台分流：AVR 用 16 位别名规则，STM32 用「视图」规则
    （见 `_stm32_address_conflicts`）。

    合法例外：16 位寄存器与其字节视图同址，这是 avr-libc 的惯例 ——
    `EEAR` = `_SFR_IO16(0x21)` 与 `EEARL` = `_SFR_IO8(0x21)` 同址；
    本机数据里 24 组全是这个形态（`TCNT1`/`TCNT1L`、`ICR1`/`ICR1L` …），
    另有 `ADC`/`ADCW` 是同一个 16 位寄存器的两个官方别名。

    判定：组内**必须有 16 位寄存器**，且所有 8 位成员都是某个 16 位成员的
    `L`/`H` 视图。两个 8 位寄存器同址 = 冲突（那必然是有一个地址写错了）。

    为什么必须查：2026-09-16 发现 `PINL@0x41` 与 `EEARL@0x41`、
    `DDRL@0x42` 与 `EEARH@0x42` 撞车 —— 这是端口 H–L 地址被写错
    （记成 0x35..0x43）的**副作用**，会让 S2 寄存器审查把端口访问
    误判成 EEPROM 访问。地址表内部矛盾，比单个地址写错更该拦。
    """
    if str(payload.get("platform", "")).lower().startswith("stm32"):
        return _stm32_address_conflicts(payload)

    by_addr: dict[str, list[tuple[str, int]]] = {}
    for group in payload.get("register_groups", {}).values():
        for reg in group.get("registers", []) or []:
            by_addr.setdefault(str(reg.get("address", "")), []).append(
                (str(reg.get("name", "")), int(reg.get("size", 8) or 8)))

    out: list[str] = []
    for addr, entries in sorted(by_addr.items()):
        if len(entries) < 2:
            continue
        wide = [n for n, s in entries if s == 16]
        narrow = [n for n, s in entries if s == 8]
        odd = [n for n, s in entries if s not in (8, 16)]
        if wide and not odd and all(
                any(n in (w + "L", w + "H") for w in wide) for n in narrow):
            continue        # 16 位别名组，合法
        out.append(f"地址 {addr} 被多个寄存器占用: "
                   f"{', '.join(f'{n}({s}位)' for n, s in entries)}")
    return out


def b_zone_root() -> Path | None:
    """B 区知识库根目录（`~/.firmforge/cache/knowledge`）。

    这里放的是**生成器派生物**（known / buildable 级），不进 git；但正因为
    它不进 git、review 时看不见，才更需要同一个校验器把关 —— 生成器改了
    规则、缓存没失效，是这条链路上最容易出现的静默错误。
    """
    try:
        from firmforge.infrastructure import paths
        return paths.knowledge_cache_dir()
    except Exception:                       # 单独运行、未装包时退到默认位置
        cand = Path.home() / ".firmforge" / "cache" / "knowledge"
        return cand if cand.is_dir() else None


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def lock_problems(out_dir: Path) -> list[str]:
    """`lock.json` 自校验：输入指纹、输出指纹、生成器版本。

    分区标准 R6 要求每个 derived 目录带 lock —— 它是「这个目录能不能
    直接删掉重生成」的唯一依据。lock 与产物对不上，说明生成后文件被
    手改过，或源已经变了而缓存没重建。
    """
    lock = out_dir / "lock.json"
    if not lock.exists():
        return ["缺 lock.json（derived 目录必须带，见分区标准 R6）"]

    try:
        data = json.loads(lock.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"lock.json 不是合法 JSON: {exc}"]

    problems: list[str] = []
    for raw, want in (data.get("inputs") or {}).items():
        p = Path(raw.replace("~", str(Path.home()), 1))
        if not p.is_file():
            problems.append(f"lock.inputs 指向的文件不存在: {raw}")
        elif sha256_of(p) != want:
            problems.append(f"lock.inputs 指纹不符（源已变）: {raw}")

    out_name = data.get("output")
    if out_name:
        out = out_dir / out_name
        if not out.is_file():
            problems.append(f"lock.output 指向的文件不存在: {out_name}")
        elif sha256_of(out) != data.get("output_sha256"):
            problems.append("output_sha256 与文件不符（生成后被改过）")

    try:
        from firmforge.knowledge.extractors.stm32_registers import (
            EXTRACTOR_VERSION)
        gen = data.get("generator_version")
        if gen and gen != EXTRACTOR_VERSION:
            problems.append(
                f"生成器已升级（lock={gen}，当前={EXTRACTOR_VERSION}）"
                f"—— 数据需重新生成")
    except Exception:
        pass
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true", dest="as_json",
                    help="machine-readable output")
    ap.add_argument("--a-only", action="store_true",
                    help="只校验 A 区（跳过 ~/.firmforge 的生成物）")
    args = ap.parse_args()

    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        print(
            "jsonschema is not installed in this interpreter.\n"
            "Run with the project venv instead:\n"
            "  C:/Users/radar/.workbuddy/binaries/python/envs/mcu_agent/"
            "Scripts/python.exe scripts/check_knowledge.py",
            file=sys.stderr,
        )
        return 2

    root = find_repo_root(Path(__file__))
    data_root = root / "firmforge" / "data"
    ref_root = data_root / "knowledge" / "reference"
    boards_root = data_root / "boards"

    if not ref_root.is_dir():
        print(f"reference dir not found: {ref_root}", file=sys.stderr)
        return 1

    results: list[dict] = []

    targets: list[tuple[Path, str]] = [
        (doc, doc.relative_to(data_root).as_posix())
        for doc in sorted(ref_root.rglob("*.json"))
    ]
    b_root = None if args.a_only else b_zone_root()
    b_docs: set[Path] = set()
    if b_root is not None and b_root.is_dir():
        for doc in sorted(b_root.rglob("registers.json")):
            b_docs.add(doc)
            targets.append(
                (doc, "B区/" + doc.relative_to(b_root).as_posix()))

    for doc, rel in targets:
        rec: dict = {"file": rel, "errors": [], "semantic": []}
        results.append(rec)

        try:
            payload = json.loads(doc.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            rec["errors"].append(f"invalid JSON: {exc}")
            continue

        ref = str(payload.get("$schema", ""))
        if not ref.startswith("knowledge/"):
            rec["errors"].append(
                f"$schema must point at a project schema, got {ref!r}")
            continue

        schema_path = data_root / ref
        if not schema_path.exists():
            rec["errors"].append(f"declared schema not found: {ref}")
            continue

        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        validator = Draft202012Validator(schema)
        for err in sorted(validator.iter_errors(payload),
                          key=lambda e: list(e.path)):
            loc = "/".join(str(p) for p in err.absolute_path) or "<root>"
            rec["errors"].append(f"{loc}: {err.message}")

        # --- semantic checks JSON Schema cannot express -------------------
        board = payload.get("board")
        if board and not (boards_root / board).is_dir():
            rec["semantic"].append(
                f"board {board!r} has no firmforge/data/boards/{board}/ — "
                f"get_pin_map({board!r}) would silently return empty")

        if doc.name == "registers.json":
            rec["semantic"].extend(address_conflicts(payload))
            if doc in b_docs:
                rec["semantic"].extend(lock_problems(doc.parent))

    # --- cross-file: registers.mcu must agree with pins.mcu ---------------
    for chip_dir in sorted(p for p in ref_root.iterdir() if p.is_dir()):
        seen: dict[str, str] = {}
        for name in ("registers.json", "pins.json"):
            p = chip_dir / name
            if not p.exists():
                continue
            try:
                mcu = json.loads(p.read_text(encoding="utf-8")).get("mcu")
            except json.JSONDecodeError:
                continue
            if mcu:
                seen[name] = str(mcu)
        if len(set(seen.values())) > 1:
            results.append({
                "file": f"{chip_dir.name}/ (cross-file)",
                "errors": [],
                "semantic": [f"mcu differs between files: {seen}"],
            })

    failures = [r for r in results if r["errors"] or r["semantic"]]

    if args.as_json:
        print(json.dumps({"ok": not failures, "results": results},
                         indent=2, ensure_ascii=False))
    else:
        for r in results:
            bad = r["errors"] or r["semantic"]
            print(f"[{'FAIL' if bad else 'OK  '}] {r['file']}")
            for e in r["errors"]:
                print(f"         schema:   {e}")
            for s in r["semantic"]:
                print(f"         semantic: {s}")
        print("-" * 60)
        print(f"结果: {len(results) - len(failures)}/{len(results)} 通过, "
              f"{len(failures)} 失败")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
