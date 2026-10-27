"""STM32 SWD 探针走的是「读 DBGMCU_IDCODE」，不是「认 USB VID/PID」。

背景（2026-10-27）：`ff detect` 认不到 DAPLink，报告说"走 VID/PID 路线"。
核对发现根因更靠前 —— `_scan_usb()` 只枚举 **COM 口**，而 CMSIS-DAP 是 HID
设备、没有 COM 口，所以往 VID/PID 表里加 (0x0D28, 0x0204) 也永远命中不了。
而且探针在位只证明"插了个调试器"，不证明目标板是什么，必须读到芯片自己
吐的 IDCODE 才算硬件身份证据。

这里锁住四件事：
  1. DEV_ID 与 board.yaml 声明一致 → 出候选；不一致 → 不出、且留下说明；
  2. 「没有探针」与「探针在但目标无响应」区别对待（前者静默，后者报告）；
  3. 多块板卡声明同一个 DEV_ID → 返回多候选、board_id=None（不猜）；
  4. 探测脚本必须自己写 `shutdown` —— 少了它 openocd 会挂到超时，
     而报出来的原因会是"探针未连接或目标未上电"，把真因藏掉。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from firmforge.core.board_detector import BoardDetector
from firmforge.core.resources import boards_dir as default_boards_dir
from firmforge.providers.stm32.debug import OcdRun


#: 实测值：DBGMCU_IDCODE = 0x20036450（REV_ID=0x2003 Rev V / DEV_ID=0x450）
_REAL_IDCODE = 0x20036450


def _run_ok(idcode: int = _REAL_IDCODE) -> OcdRun:
    return OcdRun(
        ok=True,
        stdout=f'CMSIS-DAP: Serial# = 37FFE105\nFF_IDCODE=0x{idcode:08X}\nFF_DONE=1\n',
        elapsed_ms=400.0,
    )


def _run_no_probe() -> OcdRun:
    return OcdRun(
        ok=False,
        stderr="Error: unable to find a matching CMSIS-DAP device\n",
        error="OpenOCD 会话未跑完（缺 FF_DONE 标记）：unable to find a matching CMSIS-DAP device",
    )


def _run_target_offline() -> OcdRun:
    return OcdRun(
        ok=False,
        stderr="Error: init mode failed (unable to connect to the target)\n",
        error="OpenOCD 会话未跑完（缺 FF_DONE 标记）：init mode failed",
    )


@pytest.fixture()
def detector() -> BoardDetector:
    return BoardDetector(boards_dir=Path(default_boards_dir()))


@pytest.fixture()
def fake_swd(monkeypatch):
    """让 _probe_stm32 用假的 OpenOCD 结果，并记录收到的脚本。"""
    import firmforge.providers.stm32.debug as debug_mod
    import firmforge.providers.stm32.toolchain as tc_mod

    state: dict = {"script": "", "calls": 0, "runs": []}

    class _Tc:
        openocd = "openocd"

        def problems(self) -> list[str]:
            return []

    def _fake_run_script(script, *, board_config, toolchain=None, timeout=90.0):
        state["script"] = script
        state["calls"] += 1
        runner = state["runs"][state["calls"] - 1]
        return runner() if callable(runner) else runner

    monkeypatch.setattr(debug_mod, "run_script", _fake_run_script)
    monkeypatch.setattr(tc_mod, "resolve_toolchain", lambda: _Tc())
    monkeypatch.setattr(
        BoardDetector, "_stm32_boards",
        lambda self: state.get("boards") or [("gc_h743", {"mcu": {"dev_id": "0x450"}})])
    state["state"] = state
    state["set_runs"] = lambda runs: state.__setitem__("runs", list(runs))
    return state


# ---------------------------------------------------------------------------
# 命中 / 未命中
# ---------------------------------------------------------------------------

def test_matching_dev_id_yields_candidate(detector, fake_swd):
    fake_swd["set_runs"]([_run_ok()])
    cands, notes = detector._probe_stm32()

    assert len(cands) == 1
    assert cands[0].board_id == "gc_h743"
    assert cands[0].source == "swd_probe"
    # 0.85 而不是 AVR 签名直读的 0.95：DEV_ID 只能定到系列
    assert cands[0].confidence == 0.85
    assert cands[0].details["dev_id"] == "0x450"
    assert cands[0].details["rev_id"] == "0x2003"
    assert "37FFE105" in cands[0].details["probe"]
    assert notes == []


def test_dev_id_mismatch_is_reported_not_silently_dropped(detector, fake_swd):
    """探针连的是另一颗芯片 —— 必须说出来，否则用户只会看到"没检测到"。"""
    fake_swd["set_runs"]([_run_ok((0x2003 << 16) | 0x413)])
    cands, notes = detector._probe_stm32()

    assert cands == []
    assert len(notes) == 1
    assert "0x413" in notes[0] and "0x450" in notes[0]
    assert "另一颗芯片" in notes[0]


# ---------------------------------------------------------------------------
# 「没有探针」vs「探针在、目标无响应」
# ---------------------------------------------------------------------------

def test_missing_probe_is_silent(detector, fake_swd):
    """没插探针 = 这条路不适用，不该在每次 detect 里留一条告警。"""
    fake_swd["set_runs"]([_run_no_probe()])
    cands, notes = detector._probe_stm32()

    assert cands == []
    assert notes == [], f"没有探针时不该报噪声：{notes}"


def test_probe_present_but_target_offline_is_reported(detector, fake_swd):
    """探针在、目标没上电 —— 处置完全不同（查供电/接线），必须报。"""
    fake_swd["set_runs"]([_run_target_offline()])
    cands, notes = detector._probe_stm32()

    assert cands == []
    assert len(notes) == 1
    assert "gc_h743" in notes[0]
    assert "init mode failed" in notes[0]


# ---------------------------------------------------------------------------
# 多板卡同 DEV_ID：不猜
# ---------------------------------------------------------------------------

def test_two_boards_sharing_dev_id_return_both(detector, fake_swd):
    """H742/743/753/750 同为 0x450；注册表里再加一块 H7 就分不清了。"""
    fake_swd["boards"] = [
        ("gc_h743", {"mcu": {"dev_id": "0x450"}}),
        ("gc_h750", {"mcu": {"dev_id": "0x450"}}),
    ]
    fake_swd["set_runs"]([_run_ok(), _run_ok()])
    cands, notes = detector._probe_stm32()

    assert [c.board_id for c in cands] == ["gc_h743", "gc_h750"]
    assert notes == []


def test_pipeline_detect_does_not_pick_when_ambiguous(detector, fake_swd):
    """两个候选时 board_id 必须留空，交给调用方指定。"""
    fake_swd["boards"] = [
        ("gc_h743", {"mcu": {"dev_id": "0x450"}}),
        ("gc_h750", {"mcu": {"dev_id": "0x450"}}),
    ]
    fake_swd["set_runs"]([_run_ok(), _run_ok()])

    result = detector.detect()

    assert result.board_id is None
    assert sorted(result.boards) == ["gc_h743", "gc_h750"]


# ---------------------------------------------------------------------------
# 脚本本身
# ---------------------------------------------------------------------------

def test_script_shuts_down_the_session(detector, fake_swd):
    """🔴 缺 shutdown 会让 openocd 挂到超时，并报成"探针未连接"。

    实测踩过：脚本尾部没有 shutdown 时，15 s 超时返回
    「探针未连接或目标未上电？」—— 探针明明插着，真因是脚本没退出。
    """
    fake_swd["set_runs"]([_run_ok()])
    detector._probe_stm32()

    assert "shutdown" in fake_swd["script"]
    assert "FF_DONE=1" in fake_swd["script"]
    # mrw 而不是 mdw：mdw 在 -f 脚本上下文里不产生输出（已踩过）
    assert "mrw 0x5C001000" in fake_swd["script"]
    assert "mdw" not in fake_swd["script"]


def test_script_restores_cpu_run_state(detector, fake_swd):
    """halt 过就必须 resume —— detect 不该把板子留在停摆状态。"""
    fake_swd["set_runs"]([_run_ok()])
    detector._probe_stm32()
    assert "resume" in fake_swd["script"]


# ---------------------------------------------------------------------------
# 优先级：AVR 优先，不为 SWD 多付一次 OpenOCD 启动
# ---------------------------------------------------------------------------

def test_avr_hit_short_circuits_before_swd(detector, monkeypatch):
    """Mega 插着时 detect 应直接返回，不启动 OpenOCD（省约 0.4 s）。"""
    from firmforge.core.board_detector import BoardCandidate

    monkeypatch.setattr(
        BoardDetector, "_scan_usb", lambda self: [])
    monkeypatch.setattr(
        BoardDetector, "_probe_avr",
        lambda self, usb: [BoardCandidate("arduino_mega", "avr_probe:COM7", 0.95)])

    called = {"n": 0}

    def _boom(self):
        called["n"] += 1
        return [], []

    monkeypatch.setattr(BoardDetector, "_probe_stm32", _boom)

    result = detector.detect()
    assert result.board_id == "arduino_mega"
    assert called["n"] == 0, "AVR 已命中却仍启动了 SWD 探测 —— AVR 流程被拖慢"


# ---------------------------------------------------------------------------
# 解析辅助
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("FF_IDCODE=0x20036450", 0x20036450),
    ("FF_IDCODE=1104", 1104),
    ("no marker here", None),
    ("FF_IDCODE=NA", None),
])
def test_parse_idcode(text, expected):
    from firmforge.core.board_detector import _parse_idcode
    assert _parse_idcode(text) == expected


@pytest.mark.parametrize("raw,expected", [
    ("0x450", 0x450), (1104, 1104), (None, None), ("abc", None),
])
def test_as_int(raw, expected):
    from firmforge.core.board_detector import _as_int
    assert _as_int(raw) == expected
