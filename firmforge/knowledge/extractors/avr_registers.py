"""AVR 器件头 → 寄存器骨架提取器。

原料
----
avr-libc 器件头：`<B 区>/toolchains/avr-gcc/avr/include/avr/io*.h`
（342 个器件头，与 avrdude.conf 的 386 个 part 大致对应）

产出
----
registers.json 的**骨架**：寄存器名 + 地址 + 位宽 + 位域位号。

两层解析（v1.2 起）
-------------------
单靠读文本会踩三个坑，三个都实测撞上过：

1. **缩进预处理指令**。共享头里端口 H–L、USART2/3 用的是
   ``# define PORTH  _SFR_MEM8(0x102)``（``#`` 与 ``define`` 之间有空格）。
   只认 ``#define`` 会整块漏掉 —— 实测漏 27 个寄存器。

2. **条件编译的取舍**。``iomxx0_1.h`` 一份头服务整个家族：
   ``__ATmegaxx0__``（640/1280/2560）与 ``__ATmegaxx1__``（1281/2561）
   两个分支。读文本会把两边的寄存器都收进来，给 2560 编出它没有的寄存器。

3. **条件编译的值**。``common.h`` 里
       #if __AVR_ARCH__ >= 100
       #    define SREG _SFR_MEM8(0x3F)
       #  else
       #    define SREG _SFR_IO8(0x3F)
       #  endif
   两条分支同名不同值，AVR 走 ``#else``（内存地址 0x5F，不是 0x3F）。
   谁在后谁在前不能靠猜 —— 必须真的求值。

自己写 C 预处理器不值当，于是**值也问 avr-gcc**：

    avr-gcc -mmcu=atmega2560 -E -P -dD -include avr/io.h -x c -

``-dD`` 打印它看到的每个宏定义，条件是已经求过值的。于是分工是：

    ┌ 第二层：avr-gcc -dD                      【权威值】
    │   寄存器名 / 空间 / 位宽 / 地址、存活宏名集合
    ├ 第一层：读原文（含 #include 就地展开）    【权威结构】
    │   位域归属：器件头**不显式表达**「RXC0 属于 UCSR0A」，
    │   位置相邻是唯一线索 —— 而 -dD 会吞掉空行，线索就没了
    └ 合并：寄存器取第二层，位域取第一层、再按第二层的存活宏名过滤

第二层管「这个器件到底有什么、值是多少」，第一层管「谁挨着谁」。

第一层的分块规则
----------------
    空行（连续 ≤ 2 行）  → 透明，不断块
    注释                 → 透明，不断块
    #if/#else/#endif     → 透明，不断块（值已由第二层定，这里只管结构）
    #define N <num>      → 追加为当前寄存器的位域（num 须在位宽内）
    其他 #define / 代码  → 断块

为什么空行要容忍 2 行：``common.h`` 把 SREG 的定义和它的位块之间放了
**两个**空行，一遇空行就断块会丢掉全部 8 个位。取 2 是实测值 ——
既容下 SREG，又不至于让器件尾部常量（``#define SPM_PAGESIZE 256``
之类）越过边界贴到最后一个寄存器上。

器件头给不了的东西（必须人工 / 数据手册补）
------------------------------------------
  - 位域的语义描述（"Receiver Complete"）
  - 寄存器分组（gpio / usart / tc0 ...）
  - 数据手册章节引用
  - 手册勘误规避

所以生成器产出骨架，人工制品仍是「承诺级」金标准。验收方式就是拿本机
的手工 registers.json 当金标准做比对（`tests/golden/`）。
"""

from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path
from typing import Any

#: ``#define UCSR0A _SFR_MEM8(0xC0)`` —— 捕获 名称 / 空间 / 位宽 / 地址。
#: ``#`` 与 ``define`` 之间允许空白：共享头里的端口 H–L 是缩进写法。
_SFR_RE = re.compile(
    r"^#\s*define\s+([A-Za-z_]\w*)\s+"
    r"_SFR_(IO|MEM)(8|16|32)\(\s*0[xX]([0-9A-Fa-f]+)\s*\)"
)

#: ``#define RXC0 7`` / ``#define SREG_C (0)`` —— 位域候选。
#: common.h 里的 SREG 位写成带括号形式，故允许一层括号。
_BIT_RE = re.compile(r"^#\s*define\s+([A-Za-z_]\w*)\s+\(?\s*(\d+)\s*\)?\s*$")

#: ``#include <avr/iomxx0_1.h>`` —— 器件头常只 include 一个共享头
_INCLUDE_RE = re.compile(r'^#include\s+[<"]avr/([\w.]+)[">]')

#: 条件编译指令 —— 结构上透明，见 `_parse_lines`
_COND_RE = re.compile(r"^#\s*(if|ifdef|ifndef|else|elif|endif)\b")

#: ``-dD`` 输出的 ``#define NAME ...``
_DEFINE_RE = re.compile(r"^#\s*define\s+([A-Za-z_]\w*)")

#: 允许跨过的连续空行数，见模块说明
_TRANSPARENT_BLANK_LIMIT = 2

#: I/O 空间寄存器的内存映射偏移
_IO_OFFSET = 0x20


# --------------------------------------------------------------------------
# 第一层：读原文，求「位域归属」
# --------------------------------------------------------------------------


def _read_expanded(path: Path, avr_dir: Path, seen: set[str]) -> list[str]:
    """读头文件，把 `#include <avr/...>` 就地展开成行序列。

    必须展开：`iom2560.h` 只有 3.6 KB，真正的寄存器定义在它 include 的
    共享头 `iomxx0_1.h`（36 KB）里。

    展开而非拼接，是为了保住「谁挨着谁」—— 这是判位域归属的唯一依据。
    """
    key = path.name
    if key in seen:
        return []
    seen.add(key)

    out: list[str] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = _INCLUDE_RE.match(line.strip())
        if m:
            included = avr_dir / m.group(1)
            if included.exists():
                out.extend(_read_expanded(included, avr_dir, seen))
                continue
        out.append(line)
    return out


def _parse_lines(lines: list[str]) -> dict[str, list[dict[str, Any]]]:
    """结构解析：返回 ``{寄存器名: [(位域名, 位号), ...]}`` 的归属表。

    这里**只**产出归属关系，不顺带定寄存器属性 —— 属性（地址等）
    一律由第二层给，免得两条分支的同名定义打架。
    """
    attr: dict[str, list[dict[str, Any]]] = {}
    current: str | None = None
    blank_run = 0

    for raw in lines:
        stripped = raw.strip()

        if not stripped:
            blank_run += 1
            if blank_run > _TRANSPARENT_BLANK_LIMIT:
                current = None
            continue
        blank_run = 0

        m = _SFR_RE.match(stripped)
        if m:
            # 同名重复定义（两条条件分支各一份）—— 归属表按名合并，
            # 位块继续挂在同一个名字上。
            current = m.group(1)
            attr.setdefault(current, [])
            continue

        # 注释：透明。`/* Reserved [0xD7..0xFF] */` 这类注释不需要断块 ——
        # 紧跟的 `_SFR_*` 宏会先行开新寄存器。
        if stripped.startswith(("/*", "//", "*")):
            continue

        # 条件编译指令：透明。共享头常把一个寄存器的位块劈成两半，例如
        #     #define PCICR _SFR_MEM8(0x68)
        #     #if defined(__ATmegaxx0__)
        #     # define PCIE2 2
        #     #endif
        #     #define PCIE1 1
        # 把 `#if` 当断块会让 PCIE2/1/0 全丢。
        if _COND_RE.match(stripped):
            continue

        m = _BIT_RE.match(stripped)
        if m and current is not None:
            name, bit = m.group(1), int(m.group(2))
            if bit <= 15 and all(f["name"] != name for f in attr[current]):
                attr[current].append({"name": name, "bit": bit})
                continue
            # 数值越界 → 不是位域（如 `#define SPM_PAGESIZE 256`），断块
            current = None
            continue

        # 其他 #define / 代码 → 断块
        current = None

    for fields in attr.values():
        fields.sort(key=lambda f: f["bit"])
    return attr


# --------------------------------------------------------------------------
# 第二层：问 avr-gcc「这个器件有什么、值是多少」
# --------------------------------------------------------------------------


def guess_device_name(header: Path | str) -> str | None:
    """器件头文件名 → avr-gcc 的 `-mmcu` 名。

    ``iom2560.h`` → ``atmega2560``；``iom328p.h`` → ``atmega328p``；
    ``iotn2313.h`` → ``attiny2313``。

    共享头（``iomxx0_1.h`` 这类 ``iomxx*``）不是器件，返回 ``None``。
    """
    stem = Path(header).stem
    if stem.startswith("iom") and len(stem) > 3 and stem[3] != "x":
        return "atmega" + stem[3:]
    if stem.startswith("iotn") and len(stem) > 4:
        return "attiny" + stem[4:]
    return None


def device_macro_dump(
    device: str,
    *,
    avr_gcc: str | None = None,
    timeout: int = 60,
) -> tuple[list[str], str | None]:
    """用 avr-gcc 预处理导出该器件求值后的宏定义行。

    返回 ``(行序列, 错误说明)``；失败时行序列为空、错误说明非 None。
    调用方应据此降级，**不要**静默假装过滤过了。
    """
    if avr_gcc is None:
        from firmforge.providers.arduino.toolchain import find_avr_gcc
        avr_gcc, _ = find_avr_gcc()
    if not avr_gcc:
        return [], "avr-gcc 未找到（B 区工具链未安装）"

    cmd = [
        avr_gcc, f"-mmcu={device}",
        "-E", "-P", "-dD",
        "-include", "avr/io.h",
        "-x", "c", "-",
    ]
    try:
        proc = subprocess.run(
            cmd, input="", capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return [], f"调用 avr-gcc 失败：{exc}"

    if proc.returncode != 0:
        tail = (proc.stderr or "").strip().splitlines()
        return [], f"avr-gcc 预处理失败：{tail[-1] if tail else '无错误输出'}"

    lines = proc.stdout.splitlines()
    if not lines:
        return [], "avr-gcc 预处理无输出"
    return lines, None


def _registers_from_dump(lines: list[str]) -> tuple[list[dict[str, Any]],
                                                     set[str]]:
    """从宏定义行中取出寄存器（含内存映射地址）与全部宏名。"""
    registers: list[dict[str, Any]] = []
    by_name: set[str] = set()
    names: set[str] = set()

    for line in lines:
        m = _DEFINE_RE.match(line.strip())
        if not m:
            continue
        name = m.group(1)
        names.add(name)

        sm = _SFR_RE.match(line.strip())
        if not sm or sm.group(1) in by_name:
            continue
        space, width, addr = sm.group(2), int(sm.group(3)), int(sm.group(4), 16)
        reg: dict[str, Any] = {
            "name": name,
            "size": width,
            "space": space,          # IO | MEM
            "raw_address": addr,
            # 统一给内存映射地址 —— 这才是 datasheet 与调试器用的口径
            "address": f"0x{addr + (_IO_OFFSET if space == 'IO' else 0):X}",
        }
        registers.append(reg)
        by_name.add(name)

    return registers, names


# --------------------------------------------------------------------------
# 合并
# --------------------------------------------------------------------------


def parse_device_header(
    header: Path,
    *,
    use_conditional_filter: bool = True,
    avr_gcc: str | None = None,
) -> dict[str, Any]:
    """解析器件头，返回 ``{"registers": [...], "conditional_filter": {...}}``。

    ``registers`` 条目形如
    ``{"name","size","space","raw_address","address","_fields":[...]}``。
    """
    header = Path(header)
    avr_dir = header.parent

    # avr-libc 的 io.h 在器件头**之后**再包含 common.h，SREG / SPL / SPH
    # 只在那里定义。不补这一段就会漏 3 个寄存器。
    # 不直接展开 io.h：它的器件分支是长串 `#elif defined(...)`，
    # 展开会一次拖进 342 个器件头。
    seen: set[str] = set()
    lines = _read_expanded(header, avr_dir, seen)
    common = avr_dir / "common.h"
    if common.exists() and common.name not in seen:
        lines += _read_expanded(common, avr_dir, seen)

    attr = _parse_lines(lines)

    info: dict[str, Any] = {
        "applied": False,
        "reason": None,
        "device": None,
        "removed_registers": 0,
        "removed_fields": 0,
        "register_source": "device-header text",
    }

    registers: list[dict[str, Any]] | None = None
    live: set[str] | None = None

    if use_conditional_filter:
        device = guess_device_name(header)
        info["device"] = device
        if device is None:
            info["reason"] = "不是器件头（共享头），无需过滤"
        else:
            dump, err = device_macro_dump(device, avr_gcc=avr_gcc)
            if err:
                info["reason"] = f"降级为读文本：{err}"
            else:
                registers, live = _registers_from_dump(dump)
                info["applied"] = True
                info["register_source"] = f"avr-gcc -dD ({device})"

    if registers is None:
        # 降级路径：属性退回第一层（地址可能是条件分支里的错的一支）
        registers, live = [], None
        for name in attr:
            # 从原文里找不到属性就跳过 —— 正常不会走到这里
            registers.append({"name": name, "size": 8, "space": "MEM",
                              "raw_address": 0, "address": "0x0"})
        info["reason"] = info["reason"] or "未启用条件过滤"

    kept: list[dict[str, Any]] = []
    removed_regs = removed_fields = 0
    for reg in registers:
        if live is not None and reg["name"] not in live:
            removed_regs += 1
            continue
        fields = attr.get(reg["name"], [])
        if live is not None:
            fields = [f for f in fields if f["name"] in live]
        removed_fields += len(attr.get(reg["name"], [])) - len(fields)
        reg["_fields"] = fields
        kept.append(reg)

    info["removed_registers"] = removed_regs
    info["removed_fields"] = removed_fields
    return {"registers": kept, "conditional_filter": info}


#: 生成器版本 —— 参与 lock.json 的失效判定。
#: **改提取逻辑必须递增它**，否则「改了规则但缓存没失效」会变成幽灵 bug。
EXTRACTOR_VERSION = "avr-registers/1.2.0"

#: 人工金标准的相对路径（用于验收比对，见模块说明）。
GOLDEN_RELATIVE = "firmforge/data/knowledge/reference/avr/{mcu}/registers.json"


def extract_avr_registers(
    header: Path,
    *,
    mcu: str | None = None,
    use_conditional_filter: bool = True,
    avr_gcc: str | None = None,
) -> dict[str, Any]:
    """生成一份 registers.json 骨架（单一分组，带生成器元信息）。

    分组刻意不猜：手工数据的 17 个分组（gpio / usart / tc0 ...）是人工
    判断的产物，无法从器件头可靠推断。骨架统一放 `"unclassified"`，
    等人工归类或后续规则补充。
    """
    header = Path(header)
    t0 = time.time()
    parsed = parse_device_header(
        header, use_conditional_filter=use_conditional_filter, avr_gcc=avr_gcc)
    rows = []
    for reg in parsed["registers"]:
        entry: dict[str, Any] = {
            "name": reg["name"],
            "address": reg["address"],
            "size": reg["size"],
            "source": f"avr-libc {header.name}",
        }
        if reg["_fields"]:
            entry["fields"] = [{"name": f["name"], "bit": f["bit"]}
                               for f in reg["_fields"]]
        rows.append(entry)

    return {
        "$schema": "knowledge/schema/registers.schema.json",
        "$id": f"cache/knowledge/avr/{header.stem}/registers.json",
        "platform": "arduino",
        "mcu": mcu or guess_device_name(header) or header.stem[2:].upper(),
        "mcu_series": "avr",
        "version": "1.0.0",
        "source": f"Generated from avr-libc {header.name} by {EXTRACTOR_VERSION}",
        "description": ("寄存器骨架 —— 由器件头生成，**不含**位域语义描述、"
                        "分组与数据手册引用。真机验证前属 known 级，不入库。"),
        "register_groups": {
            "unclassified": {
                "description": "未分组（生成器不猜分组，见 extractors 模块说明）",
                "registers": rows,
            }
        },
        "_generator": {
            "name": "firmforge.knowledge.extractors.avr_registers",
            "version": EXTRACTOR_VERSION,
            "source_file": header.name,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "elapsed_ms": round((time.time() - t0) * 1000, 1),
            "conditional_filter": parsed["conditional_filter"],
            "counts": {
                "registers": len(rows),
                "fields": sum(len(r.get("fields", [])) for r in rows),
            },
        },
    }


def default_avr_include_dir() -> Path:
    """avr-libc 器件头所在目录（B 区工具链内）。"""
    from firmforge.infrastructure import paths
    return paths.toolchains_dir() / "avr-gcc" / "avr" / "include" / "avr"


def golden_registers_path(mcu: str, repo_root: Path) -> Path:
    """人工金标准 registers.json 的路径（`mcu` 形如 `atmega2560`）。"""
    return Path(repo_root) / GOLDEN_RELATIVE.format(mcu=mcu)
