"""AVR 芯片档案 —— 每颗芯片的全部工具链事实，单表合一。

此前同一颗芯片的事实散在五张平行表里（build 的 ``_MCU_MAP`` /
``_VARIANT_MAP`` / ``_BOARD_DEFINE_MAP``，flash 的 ``MCU_MAP`` / ``_BAUD_MAP``
/ ``_PART_PROGRAMMER``），加一颗芯片要改三处、漏一处不报错 ——
ATmega328P 之外的芯片曾被整体 fallback 成 m2560 就是这么来的。

现在一颗芯片一行，全部事实在一起：

    build 侧：mmcu（-mmcu 值）、variant（Core 变体目录）、board_define
    flash 侧：part（avrdude -p 值）、flash_baud、programmer

未登记的芯片：build 侧走 ``profile_for()`` 的最小可编译档案（与旧的
逐表 ``.get()`` 回退等价），flash 侧显式抛 FlashError（不能猜编程器）。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ChipProfile:
    """一颗 AVR 芯片的工具链事实。"""

    mmcu: str                 # avr-gcc -mmcu 值
    part: str                 # avrdude -p 值
    variant: str              # Arduino Core variant 目录
    board_define: str         # 板卡宏（-DARDUINO_AVR_*）
    flash_baud: int           # avrdude -b 值
    programmer: str           # avrdude -c 值


#: 芯片名（与 board.yaml 的 mcu.chip 一致）→ 档案
CHIP_PROFILES: dict[str, ChipProfile] = {
    "ATmega2560": ChipProfile(
        mmcu="atmega2560", part="m2560", variant="mega",
        board_define="-DARDUINO_AVR_MEGA2560",
        flash_baud=115200, programmer="wiring"),
    "ATmega328P": ChipProfile(
        mmcu="atmega328p", part="m328p", variant="standard",
        board_define="-DARDUINO_AVR_UNO",
        flash_baud=115200, programmer="arduino"),
    "ATmega328": ChipProfile(
        mmcu="atmega328p", part="m328p", variant="standard",
        board_define="-DARDUINO_AVR_UNO",
        flash_baud=115200, programmer="arduino"),
    "ATmega168P": ChipProfile(
        mmcu="atmega168p", part="m168p", variant="standard",
        board_define="-DARDUINO_AVR_UNO",
        flash_baud=19200, programmer="wiring"),
    "ATmega168": ChipProfile(
        mmcu="atmega168p", part="m168p", variant="standard",
        board_define="-DARDUINO_AVR_UNO",
        flash_baud=19200, programmer="wiring"),
    "ATmega88P": ChipProfile(
        mmcu="atmega88p", part="m88p", variant="standard",
        board_define="-DARDUINO_AVR_UNO",
        flash_baud=19200, programmer="wiring"),
    "ATmega48P": ChipProfile(
        mmcu="atmega48p", part="m48p", variant="standard",
        board_define="-DARDUINO_AVR_UNO",
        flash_baud=19200, programmer="wiring"),
    "ATmega32U4": ChipProfile(
        mmcu="atmega32u4", part="m32u4", variant="leonardo",
        board_define="-DARDUINO_AVR_LEONARDO",
        flash_baud=57600, programmer="avr109"),
}


def profile_for(chip: str) -> ChipProfile:
    """未知芯片的最小可编译档案（build 侧回退，与旧的逐表 .get() 默认值等价）。"""
    return CHIP_PROFILES.get(chip) or ChipProfile(
        mmcu=chip.lower(), part=chip.lower(), variant="standard",
        board_define="-DARDUINO_AVR_UNO",
        flash_baud=115200, programmer="wiring")
