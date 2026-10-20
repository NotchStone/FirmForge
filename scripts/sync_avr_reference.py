"""把 avr-libc 器件头的寄存器/位域同步进 A 区参考数据。

**为什么不直接覆盖。** A 区文件里有人工判断的产物：17 个分组、寄存器描述、
数据手册引用。生成器明确不猜分组（见 ``extractors`` 模块说明），覆盖会把
这些全部丢掉，再补回来又要一轮人工核对。所以这里做的是**合并** —— 现有
条目原样保留，只补器件头里有、文件里没有的东西。

**三条合并规则**，都是为了「补数据」不变成「改数据」：

1. **同名寄存器**：地址与描述不动，只补缺的位。位号已被别的名字占用则跳过。
   AVR 里同一位有两个名字是常态（``SREG`` 的 ``C`` 与 ``SREG_C``、``UCSR0C``
   的 ``UCSZ00`` 与 ``UCPHA0``），保留人工选定的那个，生成器的写法不进来。
2. **缺的寄存器**：按分组提示表归组，落不到就归 ``system``。
3. **同址 8 位别名**（``MONDR`` / ``OCDR`` @0x51）：只收一个。两个 8 位寄存器
   同址会被 ``check_knowledge`` 判成地址冲突，而 0x51 是别名不是冲突。

用法::

    python scripts/sync_avr_reference.py --mcu atmega2560 --check
    python scripts/sync_avr_reference.py --mcu atmega2560
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from firmforge.knowledge.extractors.avr_registers import (  # noqa: E402
    default_avr_include_dir,
    extract_avr_registers,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
REFERENCE_ROOT = REPO_ROOT / "firmforge" / "data" / "knowledge" / "reference" / "avr"

#: 器件头文件（``iom2560.h`` 与 ``iomxx0_1.h`` 是同一份内容的两个入口，
#: 用 MCU 专属的那份，避免拿到系列共享头里的超集）。
HEADERS = {
    "atmega2560": "iom2560.h",
    "atmega328p": "iom328p.h",
}

#: 新寄存器归组。只覆盖缺的那几个；器件头里没有分组信息，猜不如查表。
_GROUP_HINTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^GPIOR\d$"), "system"),
    (re.compile(r"^UBRR\d$"), "usart"),
    (re.compile(r"^EIND$"), "interrupt"),
    (re.compile(r"^(SP|SPMCSR|RAMPZ|OCDR|MONDR)$"), "system"),
)


def guess_group(name: str) -> str:
    for pattern, group in _GROUP_HINTS:
        if pattern.match(name):
            return group
    return "system"


_NUM_SUFFIX = re.compile(r"\d+$")


def _family(name: str) -> str:
    """位名的族名：去掉尾部数字。``OCDR7`` → ``OCDR``、``IDRD`` → ``IDRD``。"""
    return _NUM_SUFFIX.sub("", name)


def _pick_by_family(candidates: list[dict], all_fields: list[dict]) -> dict:
    """同一位有多个名字时，选与其它位同族的那个。

    ``OCDR`` 的 bit7 在器件头里有两个名字：``OCDR7``（与 OCDR0..6 同族）
    与 ``IDRD``（读该位时的别名）。位域表要表达「这一位是什么」，同名族
    的那个才是有信息量的；按字典序或先到先得都会把 ``IDRD`` 留下、把
    连贯性破坏掉。
    """
    if len(candidates) == 1:
        return candidates[0]
    counts: dict[str, int] = {}
    for fld in all_fields:
        fam = _family(str(fld.get("name", "")))
        counts[fam] = counts.get(fam, 0) + 1
    return max(candidates,
               key=lambda f: (counts.get(_family(str(f.get("name", ""))), 0),
                              -candidates.index(f)))


def merge(mcu: str, *, check_only: bool = False,
          root: Path | None = None) -> dict[str, object]:
    """把器件头合并进 A 区文件，返回变更摘要。

    ``root`` 只为测试留口：默认写真实 A 区，测试传临时目录，避免验证
    「合并不丢数据」这件事时把真数据改坏。
    """
    header_name = HEADERS.get(mcu)
    if not header_name:
        raise SystemExit(f"未知 MCU: {mcu}（可用: {', '.join(HEADERS)}）")

    path = Path(root or REFERENCE_ROOT) / mcu / "registers.json"
    if not path.exists():
        raise SystemExit(f"参考数据不存在: {path}")

    generated = extract_avr_registers(
        default_avr_include_dir() / header_name, mcu=mcu)
    gen_regs = {r["name"]: r
                for r in generated["register_groups"]["unclassified"]["registers"]}

    payload = json.loads(path.read_text(encoding="utf-8"))
    groups = payload.setdefault("register_groups", {})

    # 现有寄存器 → (分组名, 条目)
    existing: dict[str, tuple[str, dict]] = {}
    for group_name, group in groups.items():
        for reg in group.setdefault("registers", []):
            existing[reg["name"]] = (group_name, reg)

    added_regs: list[str] = []
    added_bits = 0
    skipped_bits: list[tuple[str, str, int]] = []   # (寄存器, 位名, 位号)
    skipped_same_addr: list[str] = []

    # 现有 8 位寄存器的地址占用，用于规则 3
    addr_owners: dict[str, str] = {}
    for name, (_g, reg) in existing.items():
        if int(reg.get("size", 8) or 8) == 8:
            addr_owners.setdefault(str(reg.get("address", "")).lower(), name)

    # --- 规则 1：补缺的位 -------------------------------------------------
    for name, (group_name, reg) in existing.items():
        gen = gen_regs.get(name)
        if not gen:
            continue
        fields = reg.setdefault("fields", [])
        taken_names = {f.get("name", "").upper() for f in fields}
        taken_bits = {int(f.get("bit", -1)): f.get("name", "") for f in fields}
        for fld in gen.get("fields", []):
            bit = int(fld["bit"])
            fld_name = fld["name"]
            if fld_name.upper() in taken_names:
                # 同名同位：已经有了，不是差异
                continue
            if bit in taken_bits:
                # 同位不同名 = 官方别名（SREG.C / SREG_C、UCSZ00 / UCPHA0）。
                # 保留人工选定的那一个，别名的写法不进来。
                skipped_bits.append((name, fld_name, bit))
                continue
            fields.append({"name": fld_name, "bit": bit})
            taken_names.add(fld_name.upper())
            taken_bits[bit] = fld_name
            added_bits += 1
        if not fields:
            reg.pop("fields", None)
        else:
            fields.sort(key=lambda f: int(f.get("bit", 0)))

    # --- 规则 2 + 3：补缺的寄存器 -----------------------------------------
    # 同址 8 位别名只收一个，且优先收位域更全的那个：0x51 上 MONDR 没有位定义、
    # OCDR 有 9 个。按字典序先到先得会把 OCDR 丢掉。
    pending = [n for n in gen_regs if n not in existing]
    by_addr: dict[str, list[str]] = {}
    for name in pending:
        by_addr.setdefault(str(gen_regs[name].get("address", "")).lower(),
                           []).append(name)

    for addr, names in by_addr.items():
        candidates = names
        if len(names) > 1:
            # 同址多名：只留一个，优先位域更全的（0x51 上 MONDR 无位定义、
            # OCDR 有 9 个）。地址是否已被现有数据占用与这个选择无关 ——
            # 两个都缺时同样只能收一个，否则新数据自己和自己冲突。
            candidates = sorted(
                names,
                key=lambda n: (-len(gen_regs[n].get("fields") or []), n))
            for loser in candidates[1:]:
                skipped_same_addr.append(
                    f"{loser}@{gen_regs[loser].get('address')}"
                    f"（与 {candidates[0]} 同址，取位域更全的一个）")
            candidates = candidates[:1]

        for name in candidates:
            gen = gen_regs[name]
            addr_key = str(gen.get("address", "")).lower()
            size = int(gen.get("size", 8) or 8)
            if size == 8 and addr_key in addr_owners:
                skipped_same_addr.append(
                    f"{name}@{gen.get('address')}（与 {addr_owners[addr_key]} 同址）")
                continue

            entry: dict[str, object] = {
                "name": name,
                "address": gen["address"],
                "size": size,
                "description": gen.get("description", ""),
                "source": gen.get("source", f"avr-libc {header_name}"),
            }
            gen_fields = gen.get("fields") or []
            if gen_fields:
                # 同一位多个名字（OCDR.bit7 = OCDR7 / IDRD）只收同族的那个，
                # 否则新寄存器一进来就自带重复位号。
                by_bit: dict[int, list[dict]] = {}
                for fld in gen_fields:
                    by_bit.setdefault(int(fld["bit"]), []).append(fld)
                entry["fields"] = [
                    {"name": _pick_by_family(group, gen_fields)["name"],
                     "bit": bit}
                    for bit, group in sorted(by_bit.items())
                ]

            group_name = guess_group(name)
            if group_name not in groups:
                group_name = next(iter(groups))
            groups[group_name].setdefault("registers", []).append(entry)
            addr_owners.setdefault(addr_key, name)
            added_regs.append(f"{name}@{gen['address']} → {group_name}")

    total_bits = sum(len(r.get("fields") or [])
                     for g in groups.values() for r in g.get("registers", []))
    total_regs = sum(len(g.get("registers") or []) for g in groups.values())

    changed = bool(added_regs or added_bits)
    if changed and not check_only:
        stamp = time.strftime("%Y-%m-%d")
        payload.setdefault("_revision", []).append(
            f"{stamp}: 按 avr-libc {header_name} 补齐 —— "
            f"新增 {len(added_regs)} 个寄存器、{added_bits} 个位域"
            f"（分组/描述/引用沿用人工版本，只补缺项）。")
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")

    return {
        "mcu": mcu,
        "header": header_name,
        "path": str(path),
        "added_registers": added_regs,
        "added_bits": added_bits,
        "skipped_same_bit": skipped_bits,
        "skipped_same_addr": skipped_same_addr,
        "total_registers": total_regs,
        "total_bits": total_bits,
        "changed": changed,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mcu", action="append", default=None,
                    help="芯片名，可重复；缺省处理全部已知型号")
    ap.add_argument("--check", action="store_true",
                    help="只报告差异，不写文件")
    args = ap.parse_args(argv)

    mcus = args.mcu or list(HEADERS)
    rc = 0
    for mcu in mcus:
        summary = merge(mcu, check_only=args.check)
        print(f"=== {summary['mcu']} ({summary['header']}) ===")
        print(f"  寄存器 {summary['total_registers']} 个 / 位域 {summary['total_bits']} 个")
        if summary["added_registers"]:
            print(f"  新增寄存器 {len(summary['added_registers'])}:")
            for line in summary["added_registers"]:
                print(f"    + {line}")
        print(f"  补充位域 {summary['added_bits']} 个")
        if summary["skipped_same_bit"]:
            print(f"  跳过同名位 {len(summary['skipped_same_bit'])} 个"
                  f"（同一位已有别的名字）")
            for reg, fld, bit in summary["skipped_same_bit"][:6]:
                print(f"    - {reg}.{fld} (bit {bit})")
        if summary["skipped_same_addr"]:
            print(f"  跳过同址别名 {len(summary['skipped_same_addr'])} 个")
            for line in summary["skipped_same_addr"]:
                print(f"    - {line}")
        if args.check and summary["changed"]:
            rc = 1
        print(f"  {'需要同步' if summary['changed'] else '已是最新'}"
              f"{'（--check 未写入）' if args.check else ''}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
