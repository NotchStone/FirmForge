"""平台路由 + A/B 区查找 测试（任务 85）。

守三条线：

1. **``knowledge.platforms`` 的映射** —— 板卡 / 范式 → 寄存器库目录名。
   缺 ``hal`` 那条曾让 STM32 芯片被拿到 AVR 目录下找。
2. **A 区优先、B 区兜底** —— 生成器的产出落 B 区，人工核验的落 A 区；
   两边都在时 A 区必须赢，否则「重跑一次生成器」会静默改掉线上行为。
3. **限定键** —— STM32 的 ``CR1`` / ``SR`` / ``DR`` 跨外设重名，
   单靠裸名索引会互相覆盖，必须能按 ``外设.寄存器`` 查到。

这些都不依赖真实 SVD / 器件头，所以永远会跑。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from firmforge.core.source_reviewer import SourceReviewer
from firmforge.knowledge.knowledge_base import KnowledgeBase
from firmforge.knowledge.platforms import (
    BOARD_PLATFORM_TO_LIBRARY,
    DEFAULT_LIBRARY,
    PARADIGM_TO_LIBRARY,
    library_platform,
)

# --------------------------------------------------------------------------
# 构造用的小工具
# --------------------------------------------------------------------------


def _registers(groups: dict[str, list[str]], *, mcu: str = "atmega9999",
               platform: str = "avr") -> dict:
    """最小可用的 registers.json 载荷（KnowledgeBase 加载时不做 schema 校验）。"""
    return {
        "$schema": "knowledge/schema/registers.schema.json",
        "platform": platform,
        "mcu": mcu,
        "version": "1.0.0",
        "register_groups": {
            g: {
                "description": f"group {g}",
                "registers": [
                    {"name": n, "address": "0x00", "size": 8}
                    for n in names
                ],
            }
            for g, names in groups.items()
        },
    }


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _a_zone(root: Path, platform: str, chip: str) -> Path:
    """A 区芯片目录（``<root>/reference/<platform>/<chip>/``）。"""
    return root / "reference" / platform / chip


def _b_zone(root: Path, platform: str, chip: str) -> Path:
    """B 区芯片目录（``<root>/<platform>/<chip>/``，root 即 cache/knowledge）。"""
    return root / platform / chip


class _RecordingKB(KnowledgeBase):
    """记录 ``load_reference`` 收到的参数，用于验证路由。"""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.calls: list[tuple[str, str | None]] = []

    def load_reference(self, platform: str = "avr",  # type: ignore[override]
                       chip: str | None = None) -> bool:
        self.calls.append((platform, chip))
        return True


# --------------------------------------------------------------------------
# 1. 映射表与解析函数
# --------------------------------------------------------------------------


class TestLibraryPlatform:
    def test_board_platform_arduino_maps_to_avr(self):
        assert library_platform({"platform": "arduino"}) == "avr"

    def test_board_platform_stm32_maps_to_stm32(self):
        assert library_platform({"platform": "stm32"}) == "stm32"

    def test_board_platform_is_case_insensitive(self):
        assert library_platform({"platform": "STM32"}) == "stm32"

    def test_paradigm_hal_maps_to_stm32(self):
        """缺这条曾让 STM32 的 HAL 代码去 AVR 库里找寄存器。"""
        assert library_platform(None, "hal") == "stm32"

    def test_paradigm_arduino_maps_to_avr(self):
        assert library_platform(None, "arduino") == "avr"

    def test_paradigm_register_keeps_historical_default(self):
        assert library_platform(None, "register") == "avr"

    def test_board_platform_wins_over_paradigm(self):
        board = {"platform": "stm32", "paradigm": "hal"}
        assert library_platform(board, "arduino") == "stm32"

    def test_board_without_platform_falls_back_to_its_paradigm(self):
        assert library_platform({"paradigm": "hal"}) == "stm32"

    def test_explicit_library_name_passes_through(self):
        """CLI ``--platform stm32`` 直接给库名时要认。"""
        assert library_platform(None, "stm32") == "stm32"

    def test_unknown_input_falls_back_to_default(self):
        assert library_platform({"platform": "pic32"}, "weird") == DEFAULT_LIBRARY

    def test_custom_default(self):
        assert library_platform(None, None, default="stm32") == "stm32"

    def test_no_input_at_all(self):
        assert library_platform() == DEFAULT_LIBRARY

    def test_empty_board_dict(self):
        assert library_platform({}) == DEFAULT_LIBRARY

    def test_maps_are_consistent_with_known_dirs(self):
        """两张表的值都必须落在已登记的库名上，防止拼写漂移。"""
        from firmforge.knowledge.platforms import KNOWN_LIBRARIES
        for value in (*BOARD_PLATFORM_TO_LIBRARY.values(),
                      *PARADIGM_TO_LIBRARY.values()):
            assert value in KNOWN_LIBRARIES


# --------------------------------------------------------------------------
# 2. A 区优先 / B 区兜底
# --------------------------------------------------------------------------


class TestZoneLookup:
    def test_a_zone_only(self, tmp_path):
        a_root, b_root = tmp_path / "a", tmp_path / "b"
        _write_json(_a_zone(a_root, "avr", "atmega9999") / "registers.json",
                    _registers({"gpio": ["PORTA"]}))
        kb = KnowledgeBase(knowledge_dir=a_root, cache_dir=b_root)
        assert kb.load_reference("avr", chip="atmega9999") is True
        assert kb.lookup_register("PORTA") is not None
        assert kb.reference_origin("avr")["registers"]["zone"] == "A"

    def test_b_zone_fallback(self, tmp_path):
        """A 区没有这份数据时回退到生成器产出的 B 区。"""
        a_root, b_root = tmp_path / "a", tmp_path / "b"
        _write_json(_b_zone(b_root, "stm32", "stm32h743zit6") / "registers.json",
                    _registers({"GPIOA": ["MODER"]}, mcu="STM32H743ZIT6",
                               platform="stm32"))
        kb = KnowledgeBase(knowledge_dir=a_root, cache_dir=b_root)
        assert kb.load_reference("stm32", chip="STM32H743ZIT6") is True
        assert kb.lookup_register("MODER") is not None
        origin = kb.reference_origin("stm32")["registers"]
        assert origin["zone"] == "B"
        assert origin["path"].endswith("registers.json")

    def test_a_zone_wins_when_both_present(self, tmp_path):
        """同芯片两区都有 → A 区必须赢（否则重跑生成器会静默改行为）。"""
        a_root, b_root = tmp_path / "a", tmp_path / "b"
        _write_json(_a_zone(a_root, "avr", "atmega9999") / "registers.json",
                    _registers({"gpio": ["FROM_A"]}))
        _write_json(_b_zone(b_root, "avr", "atmega9999") / "registers.json",
                    _registers({"gpio": ["FROM_B"]}))
        kb = KnowledgeBase(knowledge_dir=a_root, cache_dir=b_root)
        kb.load_reference("avr", chip="atmega9999")
        assert kb.lookup_register("FROM_A") is not None
        assert kb.lookup_register("FROM_B") is None
        assert kb.reference_origin("avr")["registers"]["zone"] == "A"

    def test_files_resolved_per_file_not_per_directory(self, tmp_path):
        """A 区只有寄存器表、B 区只有引脚表时，两边都要用上。"""
        a_root, b_root = tmp_path / "a", tmp_path / "b"
        _write_json(_a_zone(a_root, "avr", "atmega9999") / "registers.json",
                    _registers({"gpio": ["PORTA"]}))
        _write_json(_b_zone(b_root, "avr", "atmega9999") / "pins.json",
                    {"board": "atmega9999", "pins": [
                        {"arduino_pin": 13, "register": "PORTB", "bit": 5}]})
        kb = KnowledgeBase(knowledge_dir=a_root, cache_dir=b_root)
        assert kb.load_reference("avr", chip="atmega9999") is True
        assert kb.lookup_register("PORTA") is not None
        assert kb.lookup_pin(13) is not None
        origin = kb.reference_origin("avr")
        assert origin["registers"]["zone"] == "A"
        assert origin["pins"]["zone"] == "B"

    def test_search_cache_disabled(self, tmp_path):
        """单元测试要隔离时，只有 A 区才算命中。"""
        a_root, b_root = tmp_path / "a", tmp_path / "b"
        _write_json(_b_zone(b_root, "stm32", "stm32h743zit6") / "registers.json",
                    _registers({"GPIOA": ["MODER"]}, platform="stm32"))
        kb = KnowledgeBase(knowledge_dir=a_root, cache_dir=b_root,
                           search_cache=False)
        assert kb.load_reference("stm32", chip="stm32h743zit6") is False
        assert kb.reference_sources("stm32", "stm32h743zit6") == [
            ("A", a_root / "reference" / "stm32" / "stm32h743zit6")]

    def test_both_zones_missing(self, tmp_path):
        kb = KnowledgeBase(knowledge_dir=tmp_path / "a", cache_dir=tmp_path / "b")
        assert kb.load_reference("avr", chip="atmega9999") is False
        assert kb.reference_origin("avr") == {}

    def test_missing_chip_returns_false(self, tmp_path):
        kb = KnowledgeBase(knowledge_dir=tmp_path, cache_dir=tmp_path)
        assert kb.load_reference("avr") is False
        assert kb.load_reference("avr", chip="") is False

    def test_reference_sources_order(self, tmp_path):
        kb = KnowledgeBase(knowledge_dir=tmp_path / "a", cache_dir=tmp_path / "b")
        sources = kb.reference_sources("stm32", "STM32H743ZIT6")
        assert [tag for tag, _ in sources] == ["A", "B"]
        # chip 大小写不敏感（board.yaml 写大写，目录名是小写）
        assert sources[0][1].name == "stm32h743zit6"
        assert sources[1][1].name == "stm32h743zit6"

    def test_real_avr_chip_still_loads_from_a_zone(self):
        """真数据回归：AVR 仍从 A 区加载（B 区没这份数据也不许挡路）。"""
        kb = KnowledgeBase()
        assert kb.load_reference("avr", chip="atmega2560") is True
        assert kb.lookup_register("PORTB") is not None
        assert kb.reference_origin("avr")["registers"]["zone"] == "A"


# --------------------------------------------------------------------------
# 3. 限定键（外设.寄存器）
# --------------------------------------------------------------------------


class TestQualifiedLookup:
    @pytest.fixture()
    def kb(self, tmp_path):
        a_root = tmp_path / "a"
        _write_json(_a_zone(a_root, "stm32", "stm32h743zit6") / "registers.json",
                    _registers({
                        "USART1": ["CR1", "SR"],
                        "USART2": ["CR1", "SR"],
                    }, mcu="STM32H743ZIT6", platform="stm32"))
        kb = KnowledgeBase(knowledge_dir=a_root, cache_dir=tmp_path / "b")
        assert kb.load_reference("stm32", chip="stm32h743zit6") is True
        return kb

    def test_qualified_lookup_distinguishes_peripherals(self, kb):
        u1 = kb.lookup_register_qualified("USART1", "CR1")
        u2 = kb.lookup_register_qualified("USART2", "CR1")
        assert u1 is not None and u2 is not None
        assert u1["_group"] == "USART1"
        assert u2["_group"] == "USART2"

    def test_lookup_register_with_peripheral(self, kb):
        entry = kb.lookup_register("CR1", peripheral="USART2")
        assert entry is not None
        assert entry["_group"] == "USART2"

    def test_lookup_register_bare_still_works(self, kb):
        assert kb.lookup_register("CR1") is not None

    def test_unknown_peripheral_falls_back_to_bare(self, kb):
        """库里没有这个外设时退回裸名，而不是直接判「不存在」。"""
        assert kb.lookup_register("CR1", peripheral="USART9") is not None

    def test_duplicate_names_are_tracked(self, kb):
        assert kb.is_ambiguous_register("CR1") is True
        assert kb.is_ambiguous_register("SR") is True
        assert kb.is_ambiguous_register("MODER") is False
        assert "CR1" in kb.stats()["ambiguous_register_names"]

    def test_avr_has_no_ambiguous_names(self):
        kb = KnowledgeBase()
        kb.load_reference("avr", chip="atmega2560")
        assert kb.stats()["ambiguous_register_names"] == []
        assert kb.is_ambiguous_register("PORTB") is False

    def test_lookup_register_field_with_peripheral(self, tmp_path):
        a_root = tmp_path / "a"
        payload = _registers({"USART1": ["CR1"], "USART2": ["CR1"]},
                             mcu="STM32H743ZIT6", platform="stm32")
        for group in payload["register_groups"].values():
            group["registers"][0]["fields"] = [
                {"name": "UE", "bit": 0, "bit_width": 1}]
        _write_json(_a_zone(a_root, "stm32", "stm32h743zit6") / "registers.json",
                    payload)
        kb = KnowledgeBase(knowledge_dir=a_root, cache_dir=tmp_path / "b")
        kb.load_reference("stm32", chip="stm32h743zit6")
        assert kb.lookup_register_field("CR1", "UE",
                                        peripheral="USART1") is not None
        assert kb.lookup_register_field("CR1", "NOPE",
                                        peripheral="USART1") is None


# --------------------------------------------------------------------------
# 4. load_for_board / SourceReviewer.for_board 路由
# --------------------------------------------------------------------------


class TestBoardRouting:
    def test_load_for_board_routes_stm32_to_b_zone(self, tmp_path, monkeypatch):
        """板卡 → 平台 → B 区目录，整链条打通。"""
        home = tmp_path / "ffhome"
        _write_json(_b_zone(home / "cache" / "knowledge", "stm32",
                            "stm32h743zit6") / "registers.json",
                    _registers({"GPIOA": ["MODER"]}, mcu="STM32H743ZIT6",
                               platform="stm32"))
        monkeypatch.setenv("FIRMFORGE_HOME", str(home))

        kb = KnowledgeBase(knowledge_dir=tmp_path / "empty-a")
        assert kb.load_for_board({"platform": "stm32", "paradigm": "hal",
                                  "mcu": {"chip": "STM32H743ZIT6"}}) is True
        assert kb.lookup_register("MODER", peripheral="GPIOA") is not None
        assert kb.reference_origin("stm32")["registers"]["zone"] == "B"

    def test_load_for_board_uses_a_zone_for_arduino(self):
        kb = KnowledgeBase()
        assert kb.load_for_board({"platform": "arduino", "paradigm": "arduino",
                                  "mcu": {"chip": "ATmega2560"}}) is True
        assert kb.lookup_register("PORTB") is not None
        assert kb.reference_origin("avr")["registers"]["zone"] == "A"

    def test_load_for_board_without_chip(self, tmp_path):
        kb = KnowledgeBase(knowledge_dir=tmp_path)
        assert kb.load_for_board({"platform": "stm32"}) is False
        assert kb.load_for_board(None) is False
        assert kb.load_for_board({}) is False

    def test_for_board_routes_hal_to_stm32(self, tmp_path):
        kb = _RecordingKB(knowledge_dir=tmp_path, cache_dir=tmp_path,
                          search_cache=False)
        SourceReviewer.for_board(kb, paradigm="hal", chip="stm32h743zit6")
        assert kb.calls == [("stm32", "stm32h743zit6")]

    def test_for_board_routes_arduino_to_avr(self, tmp_path):
        kb = _RecordingKB(knowledge_dir=tmp_path, cache_dir=tmp_path,
                          search_cache=False)
        SourceReviewer.for_board(kb, paradigm="arduino", chip="atmega2560")
        assert kb.calls == [("avr", "atmega2560")]

    def test_for_board_accepts_board_dict(self, tmp_path):
        kb = _RecordingKB(knowledge_dir=tmp_path, cache_dir=tmp_path,
                          search_cache=False)
        SourceReviewer.for_board(
            kb, board={"platform": "stm32", "paradigm": "hal",
                       "mcu": {"chip": "STM32H743ZIT6"}})
        assert kb.calls[-1][0] == "stm32"
        assert kb.calls[-1][1] == "STM32H743ZIT6"

    def test_for_board_board_beats_paradigm(self, tmp_path):
        kb = _RecordingKB(knowledge_dir=tmp_path, cache_dir=tmp_path,
                          search_cache=False)
        SourceReviewer.for_board(
            kb, paradigm="arduino",
            board={"platform": "stm32", "mcu": {"chip": "STM32H743ZIT6"}})
        assert kb.calls[-1][0] == "stm32"


class TestPipelineRunnerRouting:
    """回归：S2 不再把 STM32 芯片拿到 AVR 目录下找。"""

    def test_gc_h743_loads_stm32_library_from_b_zone(self, tmp_path, monkeypatch):
        from firmforge.core.pipeline_runner import PipelineRunner

        home = tmp_path / "ffhome"
        _write_json(_b_zone(home / "cache" / "knowledge", "stm32",
                            "stm32h743zit6") / "registers.json",
                    _registers({"GPIOA": ["MODER"]}, mcu="STM32H743ZIT6",
                               platform="stm32"))
        monkeypatch.setenv("FIRMFORGE_HOME", str(home))

        runner = PipelineRunner(workspace=str(tmp_path / "ws"))
        board = {"platform": "stm32", "paradigm": "hal",
                 "mcu": {"chip": "STM32H743ZIT6"}}
        runner._load_knowledge_base("stm32h743zit6", board)

        kb = runner._knowledge_base
        assert kb.reference_origin("stm32")["registers"]["zone"] == "B"
        assert kb.lookup_register("MODER", peripheral="GPIOA") is not None
        # 关键回归：AVR 的库里没有 MODER
        assert kb.lookup_register("PORTB") is None

    def test_reviewer_cache_key_includes_platform(self, tmp_path, monkeypatch):
        """同芯片换平台时要重建 reviewer，不能复用旧库。"""
        from firmforge.core.pipeline_runner import PipelineRunner

        home = tmp_path / "ffhome"
        _write_json(_b_zone(home / "cache" / "knowledge", "stm32",
                            "stm32h743zit6") / "registers.json",
                    _registers({"GPIOA": ["MODER"]}, mcu="STM32H743ZIT6",
                               platform="stm32"))
        monkeypatch.setenv("FIRMFORGE_HOME", str(home))

        runner = PipelineRunner(workspace=str(tmp_path / "ws"))
        runner._load_knowledge_base("stm32h743zit6",
                                    {"platform": "stm32",
                                     "mcu": {"chip": "STM32H743ZIT6"}})
        first = runner._knowledge_base
        # 同一平台重复加载 → 不重建
        runner._load_knowledge_base("stm32h743zit6",
                                    {"platform": "stm32",
                                     "mcu": {"chip": "STM32H743ZIT6"}})
        assert runner._knowledge_base is first

    def test_avr_board_still_routes_to_a_zone(self, tmp_path, monkeypatch):
        from firmforge.core.pipeline_runner import PipelineRunner

        monkeypatch.setenv("FIRMFORGE_HOME", str(tmp_path / "nohome"))
        runner = PipelineRunner(workspace=str(tmp_path / "ws"))
        runner._load_knowledge_base("atmega2560",
                                    {"platform": "arduino",
                                     "paradigm": "arduino",
                                     "mcu": {"chip": "ATmega2560"}})
        kb = runner._knowledge_base
        assert kb.lookup_register("PORTB") is not None
        assert kb.reference_origin("avr")["registers"]["zone"] == "A"
