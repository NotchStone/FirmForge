"""知识库平台路由 —— 「板卡 / 范式 → 寄存器库目录名」的唯一真源。

同一件事在项目里有三个不同的名字，必须先分清才能路由：

===========================  ==============================  ==================
概念                          取值                            用途
===========================  ==============================  ==================
``board.yaml`` 的 ``platform``  ``arduino`` / ``stm32``          provider 路由键
``board.yaml`` 的 ``paradigm``  ``arduino`` / ``hal`` / …       代码风格（S2 路由）
寄存器库目录名                  ``avr`` / ``stm32``              ``reference/<库>/<芯片>/``
===========================  ==============================  ==================

三者**不能互相推导**：``platform: arduino`` 的芯片是 AVR；而
``platform: stm32`` 是「厂商平台名」，不是「内核名」（Cortex-M7）。所以
必须有一张显式对照表，而不是散在各调用点的 ``if``。

优先级：``board.platform`` > ``paradigm`` > 默认 ``avr``。先看 board 是因为
「芯片是谁」由板卡声明决定；``paradigm`` 只在拿不到板卡定义时兜底
（例如 CLI 直接指定了范式）。
"""

from __future__ import annotations

from typing import Any

#: 拿不到任何线索时的历史默认（AVR 是本项目第一条路线）
DEFAULT_LIBRARY = "avr"

#: ``board.yaml: platform`` → 寄存器库目录名
BOARD_PLATFORM_TO_LIBRARY: dict[str, str] = {
    "arduino": "avr",
    "stm32": "stm32",
    "stc": "stc",
    "esp32": "esp32",
    "esp_idf": "esp32",
}

#: ``board.yaml: paradigm`` → 寄存器库目录名
#:
#: ``hal`` → ``stm32`` 是 2026-10-10 补的：GC-H743 的范式是 HAL（外设覆盖广，
#: 裸写寄存器边际收益不足），缺了这一条 S2 会把 STM32 芯片拿到 AVR 目录下找，
#: 结果是「寄存器全部查不到」→ 审查退化成噪声。
PARADIGM_TO_LIBRARY: dict[str, str] = {
    "arduino": "avr",
    "register": "avr",   # 裸寄存器代码，未声明平台时的历史默认
    "hal": "stm32",
    "stc": "stc",
    "esp_idf": "esp32",
}

#: 已存在的寄存器库目录名（调用方直接传库名时的白名单）
KNOWN_LIBRARIES: tuple[str, ...] = ("avr", "stm32", "stc", "esp32")


def library_platform(
    board: dict[str, Any] | None = None,
    paradigm: str | None = None,
    default: str = DEFAULT_LIBRARY,
) -> str:
    """解析出寄存器库目录名。

    Args:
        board: ``resolve_board()`` 返回的板卡定义（含 ``platform`` / ``paradigm``）。
        paradigm: 代码风格。仅当 ``board`` 给不出答案时使用。
        default: 两条线索都失效时的兜底。

    Returns:
        寄存器库目录名，如 ``"avr"`` / ``"stm32"``。
    """
    if board:
        key = str(board.get("platform") or "").strip().lower()
        if key in BOARD_PLATFORM_TO_LIBRARY:
            return BOARD_PLATFORM_TO_LIBRARY[key]
        # board 只给了 paradigm 时退回范式表
        if not paradigm:
            paradigm = board.get("paradigm")

    if paradigm:
        key = str(paradigm).strip().lower()
        if key in PARADIGM_TO_LIBRARY:
            return PARADIGM_TO_LIBRARY[key]
        if key in KNOWN_LIBRARIES:
            return key   # 调用方直接传库名（CLI --platform 走这条）

    return default


#: STM32 型号前缀长度：``STM32H743ZIT6`` 前 7 字符就是系列 ``STM32H7``
_STM32_SERIES_LEN = 7


def device_series(
    board: dict[str, Any] | None = None,
    chip: str | None = None,
) -> str | None:
    """芯片所属**系列**（目录分层用，不是内核）。来源优先级：板卡声明 > 型号推断。

    为什么要单列一层：STM32H7 与 STM32F1 的寄存器手册、SVD、HAL 版本
    完全不相干，平铺在 ``stm32/<芯片>/`` 下迟早会混用。系列的权威来源
    是 ``board.yaml: mcu.series``（GC-H743 写的是 ``stm32h7``）。

    STM32 的型号命名本身带系列：``STM32H743ZIT6`` → ``STM32H7``，与
    ``board.yaml`` 手写的值逐字相同，所以两种来源不会打架，推断只用于
    「没有板卡定义、只有芯片名」的场合（CLI、生成器、测试）。

    AVR 没有内部系列划分（ATmega/ATtiny 同属一份器件头），返回 ``avr``
    —— 与平台同名，路径上会被折叠掉一层。识别不出则返回 ``None``。
    """
    if board:
        declared = str((board.get("mcu") or {}).get("series") or "").strip()
        if declared:
            return declared.lower()

    if chip:
        name = str(chip).strip().lower()
        if name.startswith("stm32") and len(name) >= _STM32_SERIES_LEN:
            return name[:_STM32_SERIES_LEN]
        if name.startswith("at") or name.startswith("avr"):
            return "avr"
    return None
