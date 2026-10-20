"""板卡声明归一 —— 把 ``board.yaml`` 里形态不一的规格字段读成同一种类型。

**为什么需要这一层。** 「参数是数据而不是程序」的代价是同一件事允许多种
写法：``flash: 2 MB`` / ``flash: "256 KB"`` / ``flash: "32 KB (0.5 KB
bootloader)"``。消费方（编译、知识库查询、面板）只想要整数，于是每个调用点
各自 ``re.search`` 一次，或者干脆按自己熟悉的那块板卡硬编码字段名。

后一种已经出过事：``ff context`` 读 ``mcu.flash_size``，而三块板卡都写在
``specs.flash`` —— 结果是 **AVR 和 STM32 两条线的 Flash 都显示 0，且不报错**。
读数的人和写数据的人看到的是两个不同的世界，这类错误只有把字段名收进
一个函数里才不会再犯。

**边界。** 本模块只做「读」，不做校验：单位解析不出来返回 ``None`` 而不是
猜一个默认值 —— 把 AVR 的 16 MHz 套在 480 MHz 的 H743 上，比显示 unknown
危险得多。
"""

from __future__ import annotations

import re
from typing import Any

#: 容量单位。按长度降序排列，否则 ``MB`` 会先匹配到 ``B``。
_SIZE_UNITS: tuple[tuple[str, int], ...] = (
    ("GB", 1024 ** 3), ("MB", 1024 ** 2), ("KB", 1024),
    ("G", 1024 ** 3), ("M", 1024 ** 2), ("K", 1024), ("B", 1),
)

#: 频率单位。同上，``MHz`` 必须先于 ``Hz``。
_FREQ_UNITS: tuple[tuple[str, int], ...] = (
    ("GHZ", 1000 ** 3), ("MHZ", 1000 ** 2), ("KHZ", 1000), ("HZ", 1),
)

_SIZE_RE = re.compile(
    r"([\d.]+)\s*(" + "|".join(u for u, _ in _SIZE_UNITS) + r")\b",
    re.IGNORECASE,
)
_FREQ_RE = re.compile(
    r"([\d.]+)\s*(" + "|".join(u for u, _ in _FREQ_UNITS) + r")\b",
    re.IGNORECASE,
)


def _scaled(text: str, pattern: re.Pattern[str],
            units: tuple[tuple[str, int], ...]) -> int | None:
    """取第一个「数字 + 单位」并换算成基本单位。

    ``"32 KB (0.5 KB bootloader)"`` → 32768：括号里那个 0.5 KB 是 bootloader
    占用说明，不是容量本身，所以只认第一个匹配。
    """
    m = pattern.search(text)
    if not m:
        return None
    try:
        value = float(m.group(1))
    except ValueError:
        return None
    unit = m.group(2).upper()
    for name, factor in units:
        if unit == name:
            return int(round(value * factor))
    return None


def parse_size(value: Any) -> int | None:
    """``"2 MB"`` / ``"256 KB"`` / ``"32 KB (0.5 KB bootloader)"`` → 字节数。

    纯数字（``2097152``）原样返回。解析不出返回 ``None``。
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    return _scaled(text, _SIZE_RE, _SIZE_UNITS)


def parse_freq(value: Any) -> int | None:
    """``"480 MHz"`` / ``"16 MHz"`` → Hz。纯数字或解析不出时的规则同上。"""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    return _scaled(text, _FREQ_RE, _FREQ_UNITS)


def format_size(value: int | None) -> str:
    """字节数 → 人读。``2097152`` → ``"2 MB"``，``None`` → ``"unknown"``。"""
    if value is None:
        return "unknown"
    for name, factor in (("MB", 1024 ** 2), ("KB", 1024)):
        if value >= factor and value % factor == 0:
            return f"{value // factor} {name}"
    return f"{value} B"


def format_freq(value: int | None) -> str:
    """赫兹 → 人读。``480000000`` → ``"480 MHz"``，``None`` → ``"unknown"``。"""
    if value is None:
        return "unknown"
    for name, factor in (("GHz", 1000 ** 3), ("MHz", 1000 ** 2), ("kHz", 1000)):
        if value >= factor:
            scaled = value / factor
            text = f"{scaled:g}"
            return f"{text} {name}"
    return f"{value} Hz"


def board_specs(config: dict[str, Any] | None) -> dict[str, Any]:
    """把板卡定义归一成一份可比较的规格表。

    ``chip`` 保留声明原文（``STM32H743ZIT6``，给人看），``chip_key`` 是小写
    （给目录、索引、查找用）。两者混用过一次：显示层拿小写、查找层拿原文，
    结果是知识库能加载但界面显示 ``atmega2560``。

    解析不出的字段填 ``None``，不做默认值兜底 —— 默认值只属于编译层
    （``providers/arduino/build.py`` 的 16 MHz 兜底），不属于「告诉用户这块
    板子是什么」。
    """
    from firmforge.knowledge.platforms import device_series, library_platform

    cfg = config or {}
    mcu = cfg.get("mcu") or {}
    specs = cfg.get("specs") or {}
    chip = str(mcu.get("chip") or "").strip()

    return {
        "board": cfg.get("board_id") or cfg.get("board_name"),
        "chip": chip or None,
        "chip_key": chip.lower() or None,
        "platform": str(cfg.get("platform") or "").strip().lower() or None,
        "library": library_platform(cfg),
        "series": device_series(cfg, chip or None),
        "clock_hz": parse_freq(specs.get("clock")),
        "flash_bytes": parse_size(specs.get("flash")),
        "ram_bytes": parse_size(specs.get("ram")),
    }


def board_pin_list(config: dict[str, Any] | None,
                   pin_map: dict[str, Any] | None = None
                   ) -> tuple[str, list[dict[str, Any]]]:
    """列出板卡引脚，返回 ``(格式, 条目列表)``。

    两条来源必须分开说，因为**语义不同**：

    - ``"arduino"``：AVR 路线，来自 ``pins.json`` 的 ``arduino_pin`` 序号表，
      条目含 ``port`` / ``bit`` / ``register``，回答的是「Arduino 13 号脚是哪个
      端口位」。
    - ``"board_declared"``：STM32 路线，来自 ``board.yaml: pins``，条目是功能名
      到引脚名（``led1: PE7``），回答的是「板上 LED 接哪儿」。STM32 没有
      Arduino 引脚编号这回事，硬套一张 0..N 的表只会造假数据。
    """
    pins = (pin_map or {}).get("pins")
    if pins:
        items = pins.values() if isinstance(pins, dict) else pins
        out = [dict(p) for p in items if isinstance(p, dict)]
        if out:
            return "arduino", out

    declared = (config or {}).get("pins") or {}
    if isinstance(declared, dict) and declared:
        return "board_declared", [
            {"name": k, "value": v} for k, v in declared.items()
        ]
    return "none", []
