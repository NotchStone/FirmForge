"""知识库生成器（extractors）。

生成器的定位（标准 §9.2 第三步）：把「厂家原始数据 → 项目知识库」这一步
从手工抄写变成可重跑的批处理，让「新芯片从 0 到 L1 可编译」的工时下降到
分钟级。它**不替代人工判断**，只产出骨架。

按分区标准，生成器本身是 `committed`（项目知识的载体，进 A 区），
它的输出是 `derived`（进 B 区 cache/knowledge/，配 lock.json）。
"""

from firmforge.knowledge.extractors.avr_registers import (
    extract_avr_registers,
    parse_device_header,
)

__all__ = ["extract_avr_registers", "parse_device_header"]
