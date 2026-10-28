"""Unit tests for pipeline_state.py — fingerprint-driven incremental pipeline."""

import json
from pathlib import Path
from firmforge.core.pipeline_state import PipelineState, compute_fingerprints


class TestPipelineState:
    def test_empty_state_skips_nothing(self, tmp_path):
        state = PipelineState(Path(tmp_path))
        assert not state.should_skip_build({"board_id": "arduino_uno", "source": "abc", "hex": ""})

    def test_should_skip_build_board_match(self, tmp_path):
        state = PipelineState(Path(tmp_path))
        hexfile = tmp_path / "firmware.hex"
        hexfile.write_text(":00000001FF\n", encoding="utf-8")
        state.mark_done("build", hex=str(hexfile), board_id="arduino_uno")
        fps = {"board_id": "arduino_uno", "port": "COM5", "source": "abc", "hex": "def"}
        state.update_fingerprints(fps)
        state.save()

        state2 = PipelineState(Path(tmp_path))
        assert state2.should_skip_build({"board_id": "arduino_uno", "source": "abc"})

    def test_build_artifact_from_other_board_is_not_reused(self, tmp_path):
        """别的板卡编出来的 hex **不许**当成本板的构建产物。

        state 是「一个工作区一份」，产物却按 `cache/build/<board>/<app>/` 分开放。
        2026-10-28 实测：同一工作区里先 `ff build arduino_328p`，再 `ff run gc_h743`，
        S3 显示 ``[skipped] source unchanged, hex exists`` 并去烧 **AVR 的 5340 B hex**；
        那次是 OpenOCD 报 checksum mismatch 才没写进 Flash。校验和不是护栏，是运气。
        """
        state = PipelineState(Path(tmp_path))
        avr_hex = tmp_path / "cache" / "build" / "arduino_328p" / "Blink" / "firmware.hex"
        avr_hex.parent.mkdir(parents=True, exist_ok=True)
        avr_hex.write_text(":00000001FF\n", encoding="utf-8")
        # 产物来自 AVR，但指纹里的板卡已经被后来的运行写成 gc_h743 —— 正是实测现场
        state.mark_done("build", hex=str(avr_hex), board_id="arduino_328p")
        state.update_fingerprints({"board_id": "gc_h743", "source": "abc",
                                   "port": "COM9", "hex": "7ac74c58e8a4c243"})
        state.save()

        state2 = PipelineState(Path(tmp_path))
        assert not state2.should_skip_build({"board_id": "gc_h743", "source": "abc"}), \
            "把 AVR 的产物当成本板产物复用了 —— 下一步就是拿它去烧 STM32"

    def test_build_artifact_missing_forces_rebuild(self, tmp_path):
        """hex 被删掉之后**不许**再跳 S3 —— 指纹没变也一样。

        2026-10-28 实测：清掉 `cache/build/gc_h743/hello_blink/` 后重跑，
        S3 以「source unchanged, hex exists」为由跳过并报 BUILD PASSED，
        紧接着汇总行打印「!! 产物不存在」。缓存目录是派生物、本来就允许整块删，
        所以这条路径必须能自愈：产物不在就重编，而不是宣布有固件。
        """
        state = PipelineState(Path(tmp_path))
        hexfile = tmp_path / "cache" / "firmware.hex"
        hexfile.parent.mkdir(parents=True, exist_ok=True)
        hexfile.write_text(":00000001FF\n", encoding="utf-8")
        state.mark_done("build", hex=str(hexfile), board_id="gc_h743")
        state.update_fingerprints({"board_id": "gc_h743", "source": "abc",
                                   "port": "COM9", "hex": "def"})
        state.save()

        fps = {"board_id": "gc_h743", "source": "abc"}
        assert PipelineState(Path(tmp_path)).should_skip_build(fps)

        hexfile.unlink()                      # 等价于清构建缓存
        state3 = PipelineState(Path(tmp_path))
        assert not state3.should_skip_build(fps), \
            "产物已不存在却仍然跳过 —— 会对外宣布一份不存在的固件"

    def test_board_change_invalidates_build(self, tmp_path):
        state = PipelineState(Path(tmp_path))
        fps = {"board_id": "arduino_uno", "port": "COM5", "source": "abc", "hex": "def"}
        state.update_fingerprints(fps)
        state.save()

        state2 = PipelineState(Path(tmp_path))
        assert not state2.should_skip_build({"board_id": "arduino_nano", "source": "abc"})

    def test_port_change_invalidates_flash(self, tmp_path):
        state = PipelineState(Path(tmp_path))
        fps = {"board_id": "arduino_uno", "port": "COM5", "source": "abc", "hex": "def"}
        state.update_fingerprints(fps)
        state.save()

        state2 = PipelineState(Path(tmp_path))
        assert not state2.should_skip_flash({"board_id": "arduino_uno", "port": "COM8", "source": "abc", "hex": "def"})

    def test_fingerprints_persistence(self, tmp_path):
        state = PipelineState(Path(tmp_path))
        state.mark_done("build")
        state.mark_failed("flash", "avrdude timeout")
        state.save()

        assert Path(tmp_path, ".ff-run", "state.json").exists()
        data = json.loads(Path(tmp_path, ".ff-run", "state.json").read_text())
        assert data["stages"]["build"]["status"] == "done"
        assert data["stages"]["flash"]["status"] == "failed"
        assert data["last_error"]["stage"] == "flash"

    def test_clear_removes_file(self, tmp_path):
        state = PipelineState(Path(tmp_path))
        state.mark_done("detect")
        state.save()
        assert Path(tmp_path, ".ff-run", "state.json").exists()
        PipelineState.clear(Path(tmp_path))
        assert not Path(tmp_path, ".ff-run", "state.json").exists()


class TestLastErrorAndArtifactPath:
    """两个「状态主动误导」的回归：旧错误不清、产物路径读成内容哈希。"""

    def test_mark_done_clears_own_last_error(self, tmp_path):
        state = PipelineState(Path(tmp_path))
        state.mark_failed("test", "输出未匹配 --expected 'HB OK'")
        assert state.data["last_error"]["stage"] == "test"

        state.mark_done("test")
        assert "last_error" not in state.data, \
            "本阶段成功了还留着它自己的旧错误，ff_status 会一直报一个已解决的问题"

    def test_mark_done_keeps_other_stage_last_error(self, tmp_path):
        state = PipelineState(Path(tmp_path))
        state.mark_failed("test", "串口零字节")

        state.mark_done("build")
        assert state.data["last_error"]["stage"] == "test", \
            "S3 编译成功不代表上次 S5 采不到串口的问题解决了 —— 替别人擦账等于把没解决标成已解决"

    def test_mark_done_records_last_success(self, tmp_path):
        """成功要留正面证据，不能只靠「没有 last_error」。

        agent 看 state 时常要判断「这个 done 是刚才跑出来的，还是几天前留下的」，
        擦掉 last_error 之后什么都不表示。这条同时是这个字段的可读性回归：
        旧版 mark_done 不写 last_success，读到没有该字段就知道对方跑的是旧代码。
        """
        state = PipelineState(Path(tmp_path))
        state.mark_failed("test", "输出未匹配")
        state.mark_done("test")

        ok = state.data["last_success"]
        assert ok["stage"] == "test"
        assert len(ok["at"]) == 19, f"时间戳要能直接看：{ok['at']}"

    def test_mark_done_clears_stage_entry_error(self, tmp_path):
        state = PipelineState(Path(tmp_path))
        state.mark_failed("flash", "checksum mismatch")
        state.mark_done("flash", bytes_written=14932)
        entry = state.data["stages"]["flash"]
        assert entry["status"] == "done"
        assert "error" not in entry
        assert entry["bytes_written"] == 14932

    def test_build_artifact_path_returns_path_not_hash(self, tmp_path):
        state = PipelineState(Path(tmp_path))
        assert state.build_artifact_path() == ""

        artifact = str(tmp_path / "firmware.hex")
        state.mark_done("build", hex=artifact, board_id="gc_h743")
        state.update_fingerprints({"hex": "64b871d1a4e08f9c"})

        assert state.build_artifact_path() == artifact, \
            ("stages.build.hex 存的是产物路径，fingerprints.hex 存的是内容哈希。"
             "拿后者当路径会让 is_file() 恒为 False，指纹也会被算成空")
