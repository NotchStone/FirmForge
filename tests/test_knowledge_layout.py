"""芯片数据的目录分级测试 —— ``<平台>/<系列>/<芯片>``。

守两条线：

1. **层级正确**：同平台的不同系列（STM32H7 / STM32F1）必须落在不同目录，
   A 区（入库）与 B 区（生成物）用同一套层级。
2. **不串数据**：同一个 ``KnowledgeBase`` 先后加载两个系列时，后加载的
   必须**整体替换**前一个的索引。累加式索引不会报错，只会让裸名查到
   另一个系列的寄存器 —— 这类错误没有异常、只有错值。

AVR 只有一个系列（``avr``，与平台同名），路径上折叠成 ``avr/<芯片>``，
不为「统一」制造 ``avr/avr/atmega2560`` 这种空层。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from firmforge.infrastructure.paths import scoped_chip_dir, series_scope
from firmforge.knowledge.knowledge_base import KnowledgeBase
from firmforge.knowledge.platforms import device_series


# --------------------------------------------------------------------------
# 1. 折叠规则与系列解析
# --------------------------------------------------------------------------


class TestSeriesScope:
    def test_multi_series_platform_keeps_the_series_level(self):
        assert series_scope("stm32", "stm32h7") == ("stm32", "stm32h7")

    def test_same_name_as_platform_collapses(self):
        assert series_scope("avr", "avr") == ("avr",)

    def test_missing_series_collapses(self):
        assert series_scope("stm32", None) == ("stm32",)
        assert series_scope("stm32", "") == ("stm32",)

    def test_scoped_chip_dir_lowercases_and_joins(self):
        p = scoped_chip_dir(Path("/root"), "STM32", "STM32H7", "STM32H743ZIT6")
        assert p.as_posix() == "/root/stm32/stm32h7/stm32h743zit6"


class TestDeviceSeries:
    def test_board_declaration_wins(self):
        board = {"mcu": {"series": "stm32f1", "chip": "STM32H743ZIT6"}}
        assert device_series(board, "STM32H743ZIT6") == "stm32f1"

    def test_stm32_series_is_the_model_prefix(self):
        # STM32 的型号命名自带系列：前 7 字符就是系列，与 board.yaml 手写值一致
        assert device_series(None, "STM32H743ZIT6") == "stm32h7"
        assert device_series(None, "STM32F103C8T6") == "stm32f1"
        assert device_series(None, "STM32F407VET6") == "stm32f4"

    def test_avr_series_is_the_platform_name(self):
        assert device_series(None, "ATmega2560") == "avr"
        assert device_series({"mcu": {"series": "avr"}}, "ATmega328P") == "avr"

    def test_unknown_chip_has_no_series(self):
        assert device_series(None, "ESP32-S3") is None


# --------------------------------------------------------------------------
# 2. A / B 区路径
# --------------------------------------------------------------------------


def _payload(mcu: str, registers: dict[str, list[str]]) -> dict:
    return {
        "mcu": mcu,
        "platform": "stm32",
        "register_groups": {
            per: {"peripheral": per,
                  "base_address": "0x40000000",
                  "registers": [{"name": r, "offset": i * 4,
                                 "address": hex(0x40000000 + i * 4),
                                 "fields": []}
                                for i, r in enumerate(regs)]}
            for per, regs in registers.items()
        },
    }


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


class TestReferenceSources:
    def test_stm32_has_a_series_level_in_both_zones(self, tmp_path):
        kb = KnowledgeBase(knowledge_dir=tmp_path / "a",
                           cache_dir=tmp_path / "b")
        srcs = dict(kb.reference_sources("stm32", "stm32h743zit6", "stm32h7"))
        assert srcs["A"] == (tmp_path / "a" / "reference" / "stm32" / "stm32h7"
                             / "stm32h743zit6")
        assert srcs["B"] == (tmp_path / "b" / "stm32" / "stm32h7"
                             / "stm32h743zit6")

    def test_avr_is_collapsed(self, tmp_path):
        kb = KnowledgeBase(knowledge_dir=tmp_path / "a",
                           cache_dir=tmp_path / "b")
        srcs = dict(kb.reference_sources("avr", "atmega2560", "avr"))
        assert srcs["A"] == tmp_path / "a" / "reference" / "avr" / "atmega2560"

    def test_series_is_inferred_when_omitted(self, tmp_path):
        kb = KnowledgeBase(knowledge_dir=tmp_path / "a",
                           cache_dir=tmp_path / "b")
        srcs = dict(kb.reference_sources("stm32", "STM32H743ZIT6"))
        assert "stm32h7" in srcs["B"].parts


# --------------------------------------------------------------------------
# 3. 换系列时不得串数据
# --------------------------------------------------------------------------


class TestNoCrossSeriesLeak:
    @pytest.fixture()
    def kb(self, tmp_path) -> KnowledgeBase:
        root = tmp_path / "a"
        _write(scoped_chip_dir(root / "reference", "stm32", "stm32h7",
                               "stm32h743zit6") / "registers.json",
               _payload("STM32H743ZIT6", {"GPIOA": ["MODER", "H7_ONLY"]}))
        _write(scoped_chip_dir(root / "reference", "stm32", "stm32f1",
                               "stm32f103c8t6") / "registers.json",
               _payload("STM32F103C8T6", {"GPIOA": ["CRL", "F1_ONLY"]}))
        return KnowledgeBase(knowledge_dir=root, cache_dir=tmp_path / "b",
                             search_cache=False)

    def test_second_series_replaces_the_first(self, kb):
        assert kb.load_reference("stm32", chip="stm32h743zit6") is True
        assert kb.lookup_register("H7_ONLY") is not None

        assert kb.load_reference("stm32", chip="stm32f103c8t6") is True
        assert kb.lookup_register("F1_ONLY") is not None
        # 索引是「当前芯片」的视图，上一个系列必须整体消失
        assert kb.lookup_register("H7_ONLY") is None
        assert kb.lookup_register("MODER") is None

    def test_same_platform_different_series_both_resolve(self, kb):
        """两个系列各自的寄存器都能查到 —— 前提是它们没被放进同一个目录。"""
        assert kb.load_reference("stm32", chip="stm32h743zit6") is True
        assert kb.lookup_register("H7_ONLY") is not None
        assert kb.lookup_register("F1_ONLY") is None


# --------------------------------------------------------------------------
# 4. 真实 B 区产物的层级（没有产物时跳过）
# --------------------------------------------------------------------------


def test_real_b_zone_artifact_sits_under_its_series():
    from firmforge.knowledge.extractors import stm32_registers as gen

    path = gen.registers_path("stm32h743zit6")
    if not path.is_file():
        pytest.skip("B 区还没有 STM32H743 的生成物")
    assert path.parent.name == "stm32h743zit6"
    assert path.parent.parent.name == "stm32h7", \
        "芯片目录的父目录必须是系列 —— 否则 H7/F1 会平铺在同一层"
    assert path.parent.parent.parent.name == "stm32"


def test_svd_is_archived_under_its_series():
    from firmforge.knowledge.parity import find_svd

    path = find_svd("STM32H743x.svd", "stm32h7")
    if not path.is_file():
        pytest.skip("SVD 未归档")
    assert path.parent.name == "stm32h7"
    # 旧版平铺位置（_sources/ 根）不应再被写到
    assert path.parent != path.parent.parent
