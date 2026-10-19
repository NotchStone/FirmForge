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
