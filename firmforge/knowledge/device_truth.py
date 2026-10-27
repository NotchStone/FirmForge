"""用 CMSIS 器件头回答「这块芯片上到底有没有这个寄存器」。

为什么需要这一层
----------------
知识库是按 SVD 生成的，SVD 没建模的寄存器在库里查不到（实测 H743 约 100
条，例如 ``TIM2.RCR``、``LTDC.CLUTWR``）。幻觉寄存器（``GPIOA.BOGUS``）在库
里同样查不到。**这两者在知识库里长得一模一样**，只靠知识库无法区分 ——
工具要么说「都对」，要么把每一个缺口都说成「你写错了」。

2026-10-27 的真实误判就出在这里：``TIM2->RCR`` 是 gcc 认的真寄存器，S2 报
``Peripheral register 'TIM2.RCR' not found``，与 ``GPIOA->BOGUS`` 的输出一字
不差。用户看到的是「工具在胡说」，但工具其实只是**不知道**，却用了断言的
语气。

器件头是独立于 SVD 的第二份证据：它由芯片厂商随 CMSIS 发布，arm-none-eabi-gcc
直接拿它编译。所以「器件头里有这个名字」≈「gcc 认为它存在」。

判据的边界
----------
器件头把寄存器定义在**结构体**里，一个类型可能被多个实例共用（``TIM2`` 与
``TIM6`` 都用 ``TIM_TypeDef``）。于是 ``TIM6->CCMR1`` 会命中 ``TIM_TypeDef.CCMR1``
而判成「存在」—— 实际 TIM6 没有 CCMR1。这是**已知的放过**，方向是「宁可漏
报，不可误杀」：本层只用来把 error 降成 warning，不用来把 warning 升级成
error。

``DMA1_Stream0->CR`` 这类实例名不是器件头里的指针宏（器件头写成 ``DMA1_TypeDef``
的 ``S0CR``），查到 ``NO_INSTANCE``，同样不下判决。
"""

from __future__ import annotations

import logging
from enum import Enum
from pathlib import Path

from firmforge.knowledge.extractors.stm32_devheader import (
    DeviceHeader,
    parse_device_header,
)

logger = logging.getLogger(__name__)


class Verdict(str, Enum):
    """器件头对「实例 + 寄存器」这对名字的回答。"""

    #: 器件头里这个实例的类型有这个成员 —— 芯片上有，只是知识库没收录
    PRESENT = "present"
    #: 实例在器件头里，但类型没有这个成员 —— 这就是幻觉
    ABSENT = "absent"
    #: 器件头里没这个实例名（可能是别的宏体系，如 ``DMA1_Stream0``）
    NO_INSTANCE = "no-instance"
    #: 压根没有器件头（未装 SDK，或非 STM32 平台）
    UNAVAILABLE = "unavailable"


class DeviceTruth:
    """器件头的只读查询层，按芯片缓存。

    构造代价约 130 ms（H743 器件头 242 实例 / 77 结构体），一次会话里只做
    一次，之后全是集合查找。

    **两份头文件都要吃**：外设（GPIO/TIM/USART）定义在器件头里，而内核块
    （SCB / DWT / SysTick / CoreDebug / NVIC）定义在 CMSIS Core 头
    （``core_cm7.h``）里 —— 后者在器件头里**一个都查不到**。只吃器件头的话，
    ``SysTick->LOADX`` 这种错只能报 warning，等于内核块内部的错字没人管。
    """

    def __init__(self, header: DeviceHeader | None, source: str = "",
                 core: tuple[str, "object | None"] | None = None) -> None:
        self._header = header
        self._source = source
        #: instance 名（**大写**）→ struct 名。器件头与 core 头合并后的全集。
        #: 键必须大写：调用方（源码审查）拿到的是 `periph.upper()`，
        #: 而 core 头里的实例名是驼峰（`SysTick` / `CoreDebug`）——
        #: 大小写敏感查表会让这两个组永远 NO_INSTANCE，等于没接进来。
        self._instances: dict[str, str] = {}
        #: struct 名 → 成员名集合（大写）。只保留名字，偏移与位域本层不用。
        self._members: dict[str, set[str]] = {}
        self._core_source = ""
        if header is not None:
            for inst_name, inst in header.instances.items():
                self._instances[inst_name.upper()] = inst.struct
            for struct, members in header.structs.items():
                self._members[struct] = {m.name.upper() for m in members}
        if core is not None:
            self._merge_core(*core)

    def _merge_core(self, text: str, name: str) -> None:
        """把 CMSIS Core 头的内核块并进来。"""
        try:
            from firmforge.knowledge.extractors.cmsis_core import (
                parse_peripheral_macros,
                parse_structs,
            )
            structs, _problems = parse_structs(text)
            macros = parse_peripheral_macros(text)
        except Exception as e:              # noqa: BLE001
            logger.warning("CMSIS Core 头解析失败（%s）：%s —— "
                           "内核块内部的错字将只能报 warning", name, e)
            return
        for inst_name, type_name, _base in macros:
            self._instances.setdefault(inst_name.upper(), type_name)
        for struct, members in structs.items():
            self._members.setdefault(
                struct, {str(m.get("name", "")).upper() for m in members})
        self._core_source = name

    # -- 属性 ------------------------------------------------------------

    @property
    def available(self) -> bool:
        """器件头是否可用。不可用时本层**不下任何判决**。"""
        return self._header is not None

    @property
    def source(self) -> str:
        """证据文件（诊断输出用）。不可用时为空串。"""
        if self._core_source and self._source:
            return f"{self._source} + {self._core_source}"
        return self._source or self._core_source

    @property
    def instance_count(self) -> int:
        return len(self._instances)

    @property
    def struct_count(self) -> int:
        return len(self._members)

    # -- 查询 ------------------------------------------------------------

    def struct_of(self, instance: str) -> str | None:
        """实例名 → 结构体类型名（``GPIOA`` → ``GPIO_TypeDef``）。

        大小写不敏感：`SysTick` 与 `SYSTICK` 是同一个实例。
        """
        return self._instances.get(instance.upper())

    def has_instance(self, instance: str) -> bool:
        return instance.upper() in self._instances

    def check(self, instance: str, register: str) -> Verdict:
        """判定「实例 + 寄存器」在芯片上是否存在。

        调用方只应在**知识库查不到**之后调用本方法 —— 库命中优先，因为库里
        带着地址与位域，比"存在"这个二值信息有用得多。
        """
        if self._header is None:
            return Verdict.UNAVAILABLE
        struct = self._instances.get(instance.upper())
        if struct is None:
            return Verdict.NO_INSTANCE
        members = self._members.get(struct)
        if members is None:
            return Verdict.NO_INSTANCE
        return (Verdict.PRESENT if register.upper() in members
                else Verdict.ABSENT)

    # -- 装载 ------------------------------------------------------------

    @classmethod
    def load(cls, chip: str | None) -> "DeviceTruth":
        """按键芯片名装载（进程内缓存）。

        找不到器件头不是错误：`ff setup` 没装 SDK 时就是这样，此时返回
        ``available=False`` 的实例，审查退化为「不知道」而不是「都错」。
        """
        key = (chip or "").lower()
        cached = _CACHE.get(key)
        if cached is not None:
            return cached

        truth = cls(None, "")
        if key:
            path = _header_path(key)
            if path is not None:
                try:
                    core = _load_core_text(key)
                    truth = cls(parse_device_header(path), Path(path).name,
                                core=core)
                    logger.debug("DeviceTruth: %s（%d 实例 / %d 结构体）",
                                 truth.source, truth.instance_count,
                                 truth.struct_count)
                except Exception as e:      # noqa: BLE001 —— 器件头格式问题
                    logger.warning("器件头解析失败（%s）：%s —— "
                                   "寄存器审查将无法区分「未收录」与「幻觉」",
                                   path, e)
        _CACHE[key] = truth
        return truth


#: chip → DeviceTruth。键是芯片名小写；空串 = 无芯片上下文的默认值。
_CACHE: dict[str, DeviceTruth] = {}


def _header_path(chip: str) -> Path | None:
    """定位本芯片的 CMSIS 器件头，没有就返回 None。"""
    try:
        from firmforge.knowledge.extractors.cmsis_instances import (
            default_device_header,
        )
        path = default_device_header(chip)
    except Exception:                   # noqa: BLE001
        return None
    if path is None:
        return None
    path = Path(path)
    return path if path.is_file() else None


#: 芯片系列 → CMSIS Core 头文件名。内核块（SCB/DWT/SysTick/CoreDebug）
#: 只在这里定义，器件头里查不到。
_CORE_HEADER_BY_SERIES = {
    "stm32h7": "core_cm7.h",
    "stm32h5": "core_cm33.h",
    "stm32f7": "core_cm7.h",
    "stm32f4": "core_cm4.h",
    "stm32f3": "core_cm4.h",
    "stm32f1": "core_cm3.h",
    "stm32f0": "core_cm0.h",
    "stm32l4": "core_cm4.h",
    "stm32l0": "core_cm0plus.h",
    "stm32g4": "core_cm4.h",
    "stm32g0": "core_cm0plus.h",
}


def _load_core_text(chip: str) -> tuple[str, str] | None:
    """读 CMSIS Core 头原文。找不到返回 None（不抛）。"""
    name = _CORE_HEADER_BY_SERIES.get(chip[:7])
    if not name:
        return None
    try:
        from firmforge.knowledge.extractors.cmsis_core import default_core_header
        path = default_core_header(name)
    except Exception:                   # noqa: BLE001
        return None
    if path is None or not Path(path).is_file():
        return None
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace"), \
            Path(path).name
    except OSError:
        return None


def clear_cache() -> None:
    """丢弃缓存（测试用）。"""
    _CACHE.clear()
