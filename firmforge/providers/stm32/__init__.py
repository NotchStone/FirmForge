"""STM32 provider —— Cortex-M 路线（与 `providers/arduino` 并列的第二条线）。

分工与 AVR 路线一致，只是工具换了：

===========  ====================  ==================
阶段           AVR 路线              STM32 路线
===========  ====================  ==================
编译           avr-gcc               arm-none-eabi-gcc
烧录           avrdude（ISP/UART）   OpenOCD（SWD/CMSIS-DAP）
知识库上游     io*.h / variants      SVD / CMSIS device header
===========  ====================  ==================

注册方式：`providers/__init__.py::_PROVIDER_REGISTRY` 加一行，核心层不动。
"""

from __future__ import annotations

__all__ = ["Stm32BuildProvider", "Stm32FlashProvider", "resolve_toolchain"]

from firmforge.providers.stm32.toolchain import resolve_toolchain

# Lazy re-exports: importing the provider classes eagerly would pull in the
# build/flash modules (and their subprocess-heavy imports) even when only the
# toolchain probe is needed, e.g. `ff doctor`.
_BUILD = "firmforge.providers.stm32.build:Stm32BuildProvider"
_FLASH = "firmforge.providers.stm32.flash:Stm32FlashProvider"


def __getattr__(name: str):
    import importlib
    if name == "Stm32BuildProvider":
        return getattr(importlib.import_module(_BUILD.split(":")[0]),
                       _BUILD.split(":")[1])
    if name == "Stm32FlashProvider":
        return getattr(importlib.import_module(_FLASH.split(":")[0]),
                       _FLASH.split(":")[1])
    raise AttributeError(name)
