"""知识库生成器（extractors）。

生成器的定位（标准 §9.2 第三步）：把「厂家原始数据 → 项目知识库」这一步
从手工抄写变成可重跑的批处理，让「新芯片从 0 到 L1 可编译」的工时下降到
分钟级。它**不替代人工判断**，只产出骨架。

按分区标准，生成器本身是 `committed`（项目知识的载体，进 A 区），
它的输出是 `derived`（进 B 区 cache/knowledge/，配 lock.json）。

两条线，各自的「权威来源」不同：

============  =============================  ==========================
线            第一来源                        第二来源（交叉验证用）
============  =============================  ==========================
``avr``        avr-gcc ``-dD`` 宏转储          器件头原文结构
``stm32``      CMSIS-SVD（XML）                CMSIS 器件头（stm32h743xx.h）
============  =============================  ==========================

两个 ``parse_device_header`` 同名但签名/返回类型完全不同（一个是
``(registers, fields)`` 元组，一个是 :class:`DeviceHeader`），所以在这里
用别名区分，不要把裸名字导出出去。
"""

from firmforge.knowledge.extractors.avr_registers import (
    extract_avr_registers,
    parse_device_header as parse_avr_device_header,
)
from firmforge.knowledge.extractors.stm32_devheader import (
    parse_device_header as parse_stm32_device_header,
)
from firmforge.knowledge.extractors.stm32_registers import (
    extract_stm32_registers,
    parse_svd,
)

__all__ = [
    "extract_avr_registers",
    "parse_avr_device_header",
    "extract_stm32_registers",
    "parse_svd",
    "parse_stm32_device_header",
]
