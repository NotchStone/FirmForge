#!/usr/bin/env python
"""生成器 ↔ 第二来源 一致性比对（CLI）。

两条线：

* ``avr``   —— 生成器 ↔ `tests/golden/` 人工参考数据
* ``stm32`` —— SVD 生成器 ↔ CMSIS 器件头（`stm32h743xx.h`）

用法::

    python scripts/knowledge_parity.py                   # 两条线都跑
    python scripts/knowledge_parity.py --platform avr
    python scripts/knowledge_parity.py --platform stm32 --json
    python scripts/knowledge_parity.py --strict          # 有问题时退出码 1

判定口径见 `firmforge/knowledge/parity.py` 模块说明。要点：
**只有「同名不同值」才是硬错**；「器件头没建模」「命名口径不同」是信息，
逐条列出供人工决定是否收编。
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
    ap = argparse.ArgumentParser(description="生成器与第二来源比对")
    ap.add_argument("--platform", choices=("avr", "stm32", "all"),
                    default="all", help="比对哪条线（默认两条都跑）")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--strict", action="store_true",
                    help="存在缺失或同名不同值时退出码非 0")
    ap.add_argument("--avr-gcc", default=None,
                    help="AVR 线的 avr-gcc 路径（不给则走默认搜索）")
    args = ap.parse_args()

    want_avr = args.platform in ("avr", "all")
    want_stm32 = args.platform in ("stm32", "all")
    payload: dict[str, list[dict]] = {}
    texts: list[str] = []
    problems = 0

    if want_avr:
        try:
            reports = parity.compare_all(REPO_ROOT, avr_gcc=args.avr_gcc)
        except FileNotFoundError as exc:
            print(f"[avr] 比对所需的文件不存在：{exc}", file=sys.stderr)
            return 2
        payload["avr"] = [r.to_dict() for r in reports]
        texts.append(parity.render_text(reports))
        problems += sum(1 for r in reports
                        if not r.covered or not r.consistent)

    if want_stm32:
        reports32 = parity.compare_stm32_all(REPO_ROOT)
        if not reports32:
            print("[stm32] 跳过：SVD 或器件头不在预期位置"
                  "（SVD 找 ~/.firmforge/cache/knowledge/_sources/，"
                  "器件头找 ~/.firmforge/packages/stm32/cmsis_device_h7/*/Include/）",
                  file=sys.stderr)
        payload["stm32"] = [r.to_dict() for r in reports32]
        if reports32:
            texts.append(parity.render_stm32_text(reports32))
        # STM32 侧的硬错只有「同名不同值」；coverage 缺口逐条列着供人工决定，
        # 不当失败条件 —— 否则「器件头没建模」会把退出码永久钉死。
        problems += sum(1 for r in reports32 if not r.consistent)

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print("\n".join(texts))

    return 1 if (args.strict and problems) else 0


if __name__ == "__main__":
    raise SystemExit(main())
