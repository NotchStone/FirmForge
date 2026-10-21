

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
