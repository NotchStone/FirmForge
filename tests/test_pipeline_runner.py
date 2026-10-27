

class TestSalientError:
    """失败信息要能被人读懂：不能把 traceback 从中间切断。"""

    def test_picks_first_error_line_not_tail(self):
        from firmforge.core.pipeline_runner import _salient_error

        stderr = (
            "OpenOCD init failed\n"
            'Traceback (most recent call last):\n'
            '  File "embedded:startup.tcl", line 1928, in program\n'
            "    program_error {** OpenOCD init failed **} 1\n"
        )
        # 尾部 200 字符会把 "call last):" 切出来，这里必须取第一句
        assert _salient_error(stderr) == "OpenOCD init failed"

    def test_falls_back_to_last_line(self):
        from firmforge.core.pipeline_runner import _salient_error

        assert _salient_error("a\nb\nc\n") == "c"

    def test_empty_input(self):
        from firmforge.core.pipeline_runner import _salient_error

        assert _salient_error("") == ""
        assert _salient_error(None) == ""

    def test_truncates_long_line(self):
        from firmforge.core.pipeline_runner import _salient_error

        assert len(_salient_error("error: " + "x" * 500)) <= 200


class TestArtifactInfo:
    """跳过构建/烧录时要能回答「烧的是不是最新固件」。

    只报 `[skipped]` 的话，这个问题只能自己去 dir 查 —— 而构建缓存在
    `cache/build/<板卡>/<项目>/` 下跨项目共享，查错目录的代价是烧错固件。
    """

    def test_reports_path_time_and_size(self, tmp_path):
        from firmforge.core.pipeline_runner import _artifact_info

        f = tmp_path / "firmware.hex"
        f.write_bytes(b":00000001FF\n")
        info = _artifact_info(str(f))
        assert info["firmware_exists"] is True
        assert info["firmware_path"] == str(f)
        assert info["firmware_size"] == 12
        assert len(info["firmware_mtime"]) == 19          # YYYY-MM-DD HH:MM:SS

    def test_missing_file_is_reported_not_hidden(self, tmp_path):
        """产物没了也要照实说 —— 静默当成"有"就是让人以为能烧。"""
        from firmforge.core.pipeline_runner import _artifact_info

        info = _artifact_info(str(tmp_path / "nope.hex"))
        assert info["firmware_exists"] is False
        assert info["firmware_path"].endswith("nope.hex")

    def test_empty_path_yields_nothing(self):
        from firmforge.core.pipeline_runner import _artifact_info

        assert _artifact_info("") == {}


class TestCliArtifactLine:
    """`_stage_extra` 要把跳过原因和复用的产物一起打出来。"""

    def _stage(self, **details):
        from firmforge.core.pipeline_runner import PipelineStage

        s = PipelineStage(stage=3, name="Build")
        s.success = True
        s.details = details
        return s

    def test_skipped_without_artifact_still_shows_reason(self):
        from firmforge.adapters.cli import _stage_extra

        txt = _stage_extra(self._stage(skipped=True, reason="source unchanged, hex exists"))
        assert "skipped" in txt and "source unchanged" in txt

    def test_skipped_build_names_the_artifact(self):
        from firmforge.adapters.cli import _stage_extra

        txt = _stage_extra(self._stage(
            skipped=True, reason="source unchanged, hex exists",
            firmware_path=r"C:/cache/app/firmware.hex",
            firmware_exists=True, firmware_mtime="2026-10-27 16:14:08",
            firmware_size=87869))
        assert "firmware.hex" in txt
        assert "87869 B" in txt
        assert "2026-10-27 16:14:08" in txt

    def test_missing_artifact_is_flagged_loudly(self):
        from firmforge.adapters.cli import _stage_extra

        txt = _stage_extra(self._stage(
            skipped=True, firmware_path=r"C:/cache/app/firmware.hex",
            firmware_exists=False))
        assert "!!" in txt and "不存在" in txt
