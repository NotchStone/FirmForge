"""S5 判定的三态边界。

核心约定：ff 只回答两件机械问题——「有没有收到字节」和「调用方给的断言命中没有」。
它不判断「这个输出是否说明功能实现了」，那一层属于 Agent / 人。
所以「采到数据但没人给断言」必须显示为 collected，不能冒充 PASS。
"""

from __future__ import annotations

import pytest

from firmforge.core.pipeline_runner import (
    VERDICT_COLLECTED,
    VERDICT_EMPTY,
    VERDICT_MISMATCH,
    VERDICT_VERIFIED,
    PipelineStage,
    _decide_verify,
)

SAMPLES = ["HEARTBEAT tick=3 uptime_ms=3016", "HEARTBEAT tick=4 uptime_ms=4019"]


class TestDecideVerify:
    def test_no_bytes_is_failure_not_pass(self):
        """端口开着却一个字节都没回来 —— 以前是 PASS，这是假通过。"""
        d = _decide_verify([], "", port="COM5", baud=115200)
        assert d.success is False
        assert d.verdict == VERDICT_EMPTY
        assert "COM5" in d.error and "115200" in d.error

    def test_samples_without_assertion_is_collected_not_pass(self):
        """采到数据但没人给断言：只是采到了，不构成验证通过。"""
        d = _decide_verify(SAMPLES, "")
        assert d.success is True
        assert d.verdict == VERDICT_COLLECTED
        assert d.pattern_match is None

    def test_expected_hit_is_verified(self):
        d = _decide_verify(SAMPLES, r"HEARTBEAT tick=\d+ uptime_ms=\d+")
        assert d.success is True
        assert d.verdict == VERDICT_VERIFIED
        assert d.pattern_match is True

    def test_expected_miss_is_failure(self):
        d = _decide_verify(SAMPLES, r"Hello World #\d+")
        assert d.success is False
        assert d.verdict == VERDICT_MISMATCH
        assert d.pattern_match is False
        assert "Hello World" in d.error

    def test_invalid_regex_is_failure_not_crash(self):
        d = _decide_verify(SAMPLES, "HEARTBEAT((")
        assert d.success is False
        assert d.verdict == VERDICT_MISMATCH
        assert "Invalid regex" in d.error

    def test_expected_shown_as_given_not_escaped(self):
        """报错里的断言必须与传入的一模一样 —— 反斜杠不许翻倍。

        用 ``repr`` 拼消息时，传入 ``\\d+`` 会显示成 ``\\\\d+``（终端里看到两个
        反斜杠），读的人第一反应是「我的正则写错了」，然后去改一个本来正确的
        东西（2026-10-28 反馈）。``\\r`` / ``\\n`` 仍要转义：它们会把一行报错撑断。
        """
        d = _decide_verify(SAMPLES, r"ZZZ_NEVER_MATCH_\d+")
        assert r"ZZZ_NEVER_MATCH_\d+" in d.error, d.error
        assert r"ZZZ_NEVER_MATCH_\\d+" not in d.error, \
            f"反斜杠被翻倍了，看起来像调用方的正则写错：{d.error}"

    def test_sample_line_newlines_stay_on_one_line(self):
        """实际输出里的换行要转义，否则一条报错被撑成多行。"""
        d = _decide_verify(["HB OK\r\nsecond"], r"NOPE_\d+")
        assert "\n" not in d.error and "\r" not in d.error, d.error
        assert r"HB OK\r\nsecond" in d.error, d.error

    def test_empty_output_with_assertion_still_reports_empty(self):
        """没数据时先报 empty，而不是报「断言没命中」——这是两件事。"""
        d = _decide_verify([], r"anything")
        assert d.verdict == VERDICT_EMPTY


class TestAssertionTarget:
    """断言必须针对周期性输出。

    实测（2026-10-26 GC-H743 首跑）：拿启动横幅 `GC-H743 boot` 当断言，
    实收 `HEARTBEAT tick=1`，判 mismatch —— 固件其实是对的。原因是 S5
    在烧录完成后才打开串口，上电时打印一次的内容结构性采不到。
    所以 mismatch 的文案必须把这条讲出来，否则下一个读日志的人还会去查硬件。
    """

    def test_one_shot_banner_assertion_is_mismatch_with_hint(self):
        samples = ["HEARTBEAT ver=1 tick=1 uptime_ms=1010"]
        d = _decide_verify(samples, r"GC-H743 boot")
        assert d.verdict == VERDICT_MISMATCH
        assert "周期性" in d.error, "mismatch 文案没说明断言该针对周期性输出"
        assert "HEARTBEAT ver=1" in d.error or "实际首行" in d.error

    def test_periodic_output_assertion_passes(self):
        samples = ["HEARTBEAT ver=1 tick=1 uptime_ms=1010"]
        d = _decide_verify(samples, r"HEARTBEAT ver=1 tick=\d+")
        assert d.verdict == VERDICT_VERIFIED


class TestBadge:
    def test_collected_badge_is_not_pass(self):
        from firmforge.adapters.cli import _stage_badge, _stage_extra

        s = PipelineStage(stage=5, name="Verify", success=True)
        s.verdict = VERDICT_COLLECTED
        s.details = {"sample_count": 3}
        assert _stage_badge(s) == "COLLECT"
        assert "expected" in _stage_extra(s)

    def test_unavailable_badge_is_skip(self):
        from firmforge.adapters.cli import _stage_badge

        s = PipelineStage(stage=5, name="Verify", success=True)
        s.verdict = "unavailable"
        s.details = {"note": "No COM port", "skipped": True}
        assert _stage_badge(s) == "SKIP"

    def test_verified_badge_is_pass(self):
        from firmforge.adapters.cli import _stage_badge

        s = PipelineStage(stage=5, name="Verify", success=True)
        s.verdict = VERDICT_VERIFIED
        assert _stage_badge(s) == "PASS"

    def test_plain_stage_falls_back_to_pass_fail(self):
        from firmforge.adapters.cli import _stage_badge

        assert _stage_badge(PipelineStage(stage=3, name="Build", success=True)) == "PASS"
        assert _stage_badge(PipelineStage(stage=3, name="Build", success=False)) == "FAIL"


class TestPipelineStageDefault:
    def test_verdict_defaults_to_empty_string(self):
        assert PipelineStage(stage=1, name="Detect").verdict == ""
