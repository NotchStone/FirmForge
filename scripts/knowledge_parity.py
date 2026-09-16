#!/usr/bin/env python
"""生成器 ↔ 人工金标准 一致性比对（CLI）。

用法::

    python scripts/knowledge_parity.py            # 文本报告
    python scripts/knowledge_parity.py --json     # 机器可读
    python scripts/knowledge_parity.py --strict   # 有「缺失」或「同名不同值」时退出码 1

判定口径见 `firmforge/knowledge/parity.py` 模块说明：
只有「缺失」与「同名不同值」是问题，「生成器多出来」不是。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from firmforge.knowledge import parity  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="生成器与金标准比对")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--strict", action="store_true",
                    help="存在缺失或同名不同值时退出码非 0")
    args = ap.parse_args()

    try:
        reports = parity.compare_all(REPO_ROOT)
    except FileNotFoundError as exc:
        print(f"比对所需的文件不存在：{exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps([r.to_dict() for r in reports],
                         ensure_ascii=False, indent=2))
    else:
        print(parity.render_text(reports))

    if args.strict and any(not r.covered or not r.consistent for r in reports):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
