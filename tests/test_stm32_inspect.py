"""`ff inspect` 的回归测试 —— 只锁「看起来正常但实际是错的」那几处。

为什么要写这些用例：inspect 的每条结论都是「一个数字 → 一个含义」，而数字本身
不携带对错。下面任何一条退化回去，命令**照常输出、退出码为 0**，人却会读错，
比直接报错危险得多。三处具体的坑：

1. **复位优先级**。IWDG1 超时会同时置 `PINRSTF`（RM0433 Table 56 第 8 行），
   按"先看 PIN"的顺序判，看门狗复位永远被误判成"按了复位键"。
2. **上电默认值 0x00FE0000**（同手册 Table 65）。固件不清标志时，这个值里的
   POR/PIN/BOR/D1/D2/CPU 六位天生是 1，照表解就会稳定给出"上电复位"。
3. **`mdw` 在 `-f` 脚本里没有输出**（实测 openocd 0.12）。改用 `mrw` 的返回值
   是唯一可行路径；有人"顺手改回 mdw"会让所有内存读数静默变成"未读到"。
"""

from __future__ import annotations

import pytest

from firmforge.providers.stm32 import inspect as ins

# RM0433 Table 65：RCC_RSR 上电复位值
_POR_DEFAULTS = 0x00FE0000


def _bits(*names: str) -> int:
    raw = 0
    for n in names:
        raw |= 1 << ins._RSR_BIT[n]
    return raw


# --------------------------------------------------------------------------
# 复位原因
# --------------------------------------------------------------------------

def test_iwdg_beats_pin_because_table56_sets_both():
    """IWDG1 超时会连带 PINRSTF —— primary 必须是 IWDG1。"""
    raw = _POR_DEFAULTS | _bits("IWDG1RSTF")
    warns: list[str] = []
    rc = ins._reset_cause(raw, warns)
    assert rc["primary"] == "IWDG1"
    assert "PIN" in rc["flags"]
    assert any("残留" in w for w in warns)


def test_power_on_beats_brownout():
    """上电会同时置 BOR；判成 BOR 会把"首次上电"说成"掉电"。"""
    raw = _bits("PORRSTF", "BORRSTF", "PINRSTF", "CPURSTF")
    rc = ins._reset_cause(raw, [])
    assert rc["primary"] == "POR"


def test_software_reset_beats_pin():
    raw = _bits("SFTRSTF", "PINRSTF", "CPURSTF")
    assert ins._reset_cause(raw, [])["primary"] == "SFT"


def test_power_on_default_value_is_declared_untrustworthy():
    """读到 0x00FE0000 = 固件从没清过标志，不能当成"本次上电复位"。"""
    warns: list[str] = []
    rc = ins._reset_cause(_POR_DEFAULTS, warns)
    assert rc["primary"] == "POR"          # 表还是照解
    assert "不可判定" in rc["note"]         # 但结论必须自我否定
    assert any("从未清过" in w for w in warns)


def test_all_flags_cleared_gives_none():
    rc = ins._reset_cause(0, [])
    assert rc["primary"] is None
    assert rc["flags"] == []


def test_missing_rsr_is_reported_not_guessed():
    warns: list[str] = []
    assert ins._reset_cause(None, warns) is None
    assert any("RCC_RSR" in w for w in warns)


# --------------------------------------------------------------------------
# 脚本生成
# --------------------------------------------------------------------------

def _script(**kw) -> str:
    req = ins.InspectRequest(**kw)
    return ins._build_script(req, [(ins.RCC_RSR, 1, 4)], warning_sink=[])


def test_freeze_must_happen_before_halt():
    """冻结位在 halt 之后设就晚了：计数器已经在跑，快照可能被复位打断。"""
    s = _script()
    freeze_at = s.index(f"mmw 0x{ins.DBGMCU_APB4FZ1:08X} 0x{ins.IWDG1_FREEZE_BIT:08X} 0x0")
    halt_at = s.index("catch {halt}")
    assert freeze_at < halt_at


def test_freeze_only_touches_its_own_bit():
    """mmw 的语义是 (old & ~clear) | set，所以只动 bit18，别的冻结位不被清。"""
    s = _script()
    assert "mrw" in s  # 先读，原值已置位则不动
    assert f"mmw 0x{ins.DBGMCU_APB4FZ1:08X} 0x0 0x{ins.IWDG1_FREEZE_BIT:08X}" in s


def test_restore_only_when_we_touched_the_bit():
    """没动过就不写 —— 位本来就是我们要的状态时，回写等于白白制造一次改动。"""
    s = _script()
    assert "if {$ff_fz_applied == 1 && $ff_fz_have == 1}" in s


def test_prior_check_never_compares_string_in_expr():
    """`expr` 里出现裸 `NA` 会报 syntax error（实测：会话在中途炸掉）。

    判断"读到了没有"必须用数字标志（ff_fz_have），不能在表达式里比字符串。
    """
    s = _script()
    assert "!= NA" not in s and "== NA" not in s
    assert "ff_fz_have" in s


def test_no_freeze_switch_clears_the_bit():
    """`--no-freeze-watchdog` 必须**主动清位**。

    OpenOCD 的 stm32h7x.cfg 在 examine-end 里无条件冻结了 IWDG1，
    所以"不写"等于"保持冻结"，开关形同虚设 —— 这是实测出来的。
    """
    s = _script(freeze_watchdog=False)
    assert f"mmw 0x{ins.DBGMCU_APB4FZ1:08X} 0x0 0x{ins.IWDG1_FREEZE_BIT:08X}" in s
    assert "} elseif {!0 && $_cur != 0} {" in s


def test_freeze_restores_prior_bit_state_not_just_clears():
    """恢复要写回原值，不能一律清零 —— DBGMCU 只在 POR 复位，
    别人（OpenOCD 的 examine-end）设的位不该被我们擦掉。"""
    s = _script()
    assert f"$ff_fz_prior & 0x{ins.IWDG1_FREEZE_BIT:08X}" in s
    assert f"mmw 0x{ins.DBGMCU_APB4FZ1:08X} $_restore 0x{ins.IWDG1_FREEZE_BIT:08X}" in s


def test_script_never_uses_mdw():
    """mdw 的输出走 command_print，-f 上下文里没有输出句柄 → 静默无输出。

    只查命令行，不查注释：注释里为了解释原因必须提到 mdw。
    """
    s = _script()
    commands = [ln.strip() for ln in s.splitlines()
                if ln.strip() and not ln.strip().startswith("#")]
    assert not any(cmd.startswith(("mdw ", "mdh ", "mdb ")) for cmd in commands)
    assert any("mrw" in cmd for cmd in commands)


def test_script_always_marks_done():
    """缺 FF_DONE 就判定会话不完整 —— 半份数据比没有更危险。"""
    assert "echo FF_DONE=1" in _script()


def test_no_resume_leaves_target_halted():
    s = _script(resume=False)
    assert "catch {resume}" not in s


# --------------------------------------------------------------------------
# 解析
# --------------------------------------------------------------------------

def test_markers_keep_lowercase_register_names():
    """`FF_REG_pc=...` 里 pc 是小写，正则写成 [A-Z0-9_] 会全部丢掉。"""
    text = "Info : noise\nFF_REG_pc=pc (/32): 0x08003A58\nFF_HALT=OK\n"
    m = ins._parse_markers(text)
    assert m["REG_pc"] == "pc (/32): 0x08003A58"
    assert m["HALT"] == "OK"


def test_mem_markers_become_address_map():
    text = "FF_MEM_0x20000154=0x00000006\nFF_MEM_0x580244D0=0x01460000\n"
    mem = ins._parse_mem(ins._parse_markers(text))
    assert mem[0x20000154] == 6
    assert mem[0x580244D0] == 0x01460000


@pytest.mark.parametrize("text,expected", [
    ("pc (/32): 0x08003A58", 0x08003A58),
    ("0x08003A58", 0x08003A58),
    ("134232664", 134232664),     # 纯十进制（另有版本只回裸数字）
    ("ERR", None),
    ("NA", None),
    ("", None),
])
def test_as_int_accepts_all_register_output_forms(text, expected):
    assert ins._as_int(text) == expected


def test_field_decode_skips_zero_bits():
    """32 位寄存器里 20 个 0 字段会把结论淹没；但置位的字段必须算对。"""
    fields = [{"name": "ENABLE", "bit": 0}, {"name": "CNTSTRT", "bit": 2},
              {"name": "SNPST", "bit": 3}, {"name": "PRESC", "bit": 9, "bit_width": 3}]
    out = ins._decode_fields(fields, 0x2561)
    names = {f["name"]: f["value"] for f in out}
    assert names == {"ENABLE": 1, "PRESC": 2}
    assert "CNTSTRT" not in names and "SNPST" not in names


# --------------------------------------------------------------------------
# 位置解析
# --------------------------------------------------------------------------

def test_addr2line_gets_thumb_bit_stripped(monkeypatch):
    """Cortex-M 的 PC 最低位是 Thumb 状态位，直接喂 addr2line 会错位一行。"""
    seen: dict[str, list[str]] = {}

    class _R:
        stdout = "busy_delay_ms\napp/main.c:90\n"

    def fake_run(cmd, **kw):
        seen["cmd"] = list(cmd)
        return _R()

    monkeypatch.setattr(ins, "run_text", fake_run)
    # 兄弟工具必须能被"找到"，否则 _location 会在起 addr2line 之前就返回
    monkeypatch.setattr(ins, "_sibling_tool", lambda gcc, name: f"/fake/{name}")
    out = ins._location("fw.elf", 0x08001C8D, _tc_with_tools(), [])
    assert "08001C8C" in " ".join(seen["cmd"])
    assert out["function"] == "busy_delay_ms"
    assert out["line"] == 90


def test_location_without_elf_does_not_pretend():
    out = ins._location(None, 0x08000000, _tc_with_tools(), [])
    assert out["pc"] == "0x08000000"
    assert out["function"] is None


class _TC:
    def __init__(self, gcc: str = "") -> None:
        self.gcc = gcc


def _tc_with_tools() -> _TC:
    """用一个存在的 exe 当"兄弟工具"的锚点，避免依赖本机 ARM 工具链。"""
    import sys
    return _TC(gcc=sys.executable)


def test_sibling_tool_returns_none_when_missing():
    import sys
    assert ins._sibling_tool(sys.executable, "nonexistent-tool") is None


def test_location_strips_addr2line_discriminator(monkeypatch):
    """`file:1261 (discriminator 1)` 是 GCC 的真实输出，不剥会把整串当文件名。"""
    class _R:
        stdout = "HAL_UART_Receive\nlib/uart.c:1261 (discriminator 1)\n"

    monkeypatch.setattr(ins, "run_text", lambda cmd, **kw: _R())
    monkeypatch.setattr(ins, "_sibling_tool", lambda gcc, name: f"/fake/{name}")
    out = ins._location("fw.elf", 0x08004F54, _tc_with_tools(), [])
    assert out["file"] == "lib/uart.c"
    assert out["line"] == 1261


# --------------------------------------------------------------------------
# 快照合理性（"读到了但全是坏值"）
# --------------------------------------------------------------------------

def _payload(sp: str | None, pc: str | None, frozen: bool | None) -> dict:
    return {"target": {"watchdog_frozen": frozen},
            "stack": {"sp": sp},
            "location": {"pc": pc} if pc else None}


def test_unfrozen_watchdog_marks_snapshot_untrustworthy():
    warns: list[str] = []
    ins._sanity_check_snapshot(_payload("0x2001FD68", "0x08004FBC", False), warns)
    assert any("看门狗未冻结" in w for w in warns)


def test_sp_equal_to_pc_is_caught():
    """实测过：目标中途复位时 PC 与 SP 会是同一个 flash 地址，命令却不报错。"""
    warns: list[str] = []
    ins._sanity_check_snapshot(_payload("0x08004FBC", "0x08004FBC", True), warns)
    assert any("SP 与 PC 相同" in w for w in warns)


def test_sp_outside_ram_is_caught():
    warns: list[str] = []
    ins._sanity_check_snapshot(_payload("0x08001ABC", "0x08004FBC", True), warns)
    assert any("不落在任何 RAM 区间" in w for w in warns)


def test_healthy_snapshot_produces_no_warning():
    warns: list[str] = []
    ins._sanity_check_snapshot(_payload("0x2001FD68", "0x08004FBC", True), warns)
    assert warns == []


# --------------------------------------------------------------------------
# 外设
# --------------------------------------------------------------------------

class _FakeKb:
    def __init__(self, groups: dict[str, list[dict]]) -> None:
        self._g = groups

    def search_registers(self, q: str, limit: int = 200):
        return self._g.get(q.upper(), []), False


def test_single_register_spec_has_no_base():
    """`--periph RCC.RSR` 时若把 RSR 的地址当 base，会印出"外设 @ 寄存器地址"。"""
    kb = _FakeKb({"RCC": [{"name": "RSR", "address": "0x580244D0", "size": 32,
                           "fields": []}]})
    plan = ins._peripheral_plan(kb, ["RCC.RSR"], [])
    assert plan[0]["base"] is None
    assert plan[0]["registers"][0]["name"] == "RSR"


def test_unknown_peripheral_warns_and_skips():
    warns: list[str] = []
    assert ins._peripheral_plan(_FakeKb({}), ["NOPE"], warns) == []
    assert any("NOPE" in w for w in warns)


# --------------------------------------------------------------------------
# ELF 选择：多份时必须拒绝猜测
# --------------------------------------------------------------------------

def _make_cache(tmp_path, *apps: str):
    root = tmp_path / "build" / "gc_h743"
    for a in apps:
        d = root / a
        d.mkdir(parents=True)
        (d / "firmware.elf").write_bytes(b"\x7fELF" + a.encode())
    return root


def _patch_cache(monkeypatch, root):
    from firmforge.infrastructure import paths
    monkeypatch.setattr(paths, "build_cache_dir", lambda: root.parent)


def test_multiple_elves_refuses_to_guess(tmp_path, monkeypatch):
    """缓存里有两份 ELF 时**不能**按修改时间猜。

    曾经取最新一份：`app/` 与 `hello_blink/` 并存时选中了 hello_blink，
    于是 `Where:` 打出一个完全合理但属于另一个固件的函数名 ——
    错的答案看起来是对的，不会有人去查。
    """
    root = _make_cache(tmp_path, "app", "hello_blink")
    _patch_cache(monkeypatch, root)
    with pytest.raises(ins.InspectError) as ei:
        ins._resolve_elf({"board_id": "gc_h743"}, ins.InspectRequest(), [])
    msg = str(ei.value)
    # 候选必须带上「怎么指定」的写法，否则等于只说了句"不行"
    assert "--app app" in msg and "--app hello_blink" in msg
    assert max(len(c) for c in ei.value.candidates) > 10


def test_app_picks_that_exact_elf(tmp_path, monkeypatch):
    root = _make_cache(tmp_path, "app", "hello_blink")
    _patch_cache(monkeypatch, root)
    got, note = ins._resolve_elf({"board_id": "gc_h743"},
                                 ins.InspectRequest(app="hello_blink"), [])
    assert got.endswith("hello_blink" + str(__import__("os").sep) + "firmware.elf")
    assert note == ""


def test_single_elf_is_used_and_still_echoed(tmp_path, monkeypatch):
    """只有一份时不算歧义，但仍要在 payload 里回显路径。"""
    root = _make_cache(tmp_path, "app")
    _patch_cache(monkeypatch, root)
    got, _note = ins._resolve_elf({"board_id": "gc_h743"}, ins.InspectRequest(), [])
    assert got and got.endswith("firmware.elf")


def test_app_and_elf_are_mutually_exclusive(tmp_path):
    with pytest.raises(ins.InspectError) as ei:
        ins._resolve_elf({"board_id": "gc_h743"},
                         ins.InspectRequest(app="app", elf="x.elf"), [])
    assert "--elf" in str(ei.value) and "--app" in str(ei.value)


def test_missing_app_lists_what_is_available(tmp_path, monkeypatch):
    root = _make_cache(tmp_path, "app", "hello_blink")
    _patch_cache(monkeypatch, root)
    with pytest.raises(ins.InspectError) as ei:
        ins._resolve_elf({"board_id": "gc_h743"},
                         ins.InspectRequest(app="nosuch"), [])
    assert "app" in " ".join(ei.value.candidates)
    assert "hello_blink" in " ".join(ei.value.candidates)


# --------------------------------------------------------------------------
# --pc 离线解析：不碰探针
# --------------------------------------------------------------------------

class _NoProbeTC:
    """只有离线路径会读到的字段 —— OpenOCD 相关一律留空。"""

    gcc = ""
    openocd = ""


def _offline_payload(monkeypatch, tmp_path, *, pc=0x08001D78,
                     apps=("app",), app="app"):
    root = _make_cache(tmp_path, *apps)
    _patch_cache(monkeypatch, root)
    monkeypatch.setattr(ins, "_load_kb", lambda cfg, w: None)
    # 会话一旦被启动就说明离线分支漏了 —— 直接炸，不要静默通过
    def _boom(*a, **kw):
        raise AssertionError("离线 --pc 不该启动 OpenOCD 会话")
    monkeypatch.setattr(ins, "run_script", _boom)
    return ins.inspect({"board_id": "gc_h743", "platform": "stm32"},
                       ins.InspectRequest(app=app, pc=pc), toolchain=_NoProbeTC())


def test_pc_mode_does_not_touch_the_probe(monkeypatch, tmp_path):
    """从串口拿到 pc 只需要 addr2line —— 绝不能连板子（会复位、冻结看门狗）。"""
    monkeypatch.setattr(ins, "_location",
                        lambda elf, pc, tc, w: {"pc": f"0x{pc:08X}",
                                                "function": "crash", "file": "a.c",
                                                "line": 12})
    p = _offline_payload(monkeypatch, tmp_path)
    assert p["mode"] == "offline"
    assert p["location"]["function"] == "crash"


def test_offline_payload_does_not_fake_hardware_fields(monkeypatch, tmp_path):
    """没连板子就不能有 sp/lr/reset_cause —— 打出来等于说"连上了"。"""
    monkeypatch.setattr(ins, "_location",
                        lambda elf, pc, tc, w: {"pc": "0x08001D78", "function": "f",
                                                "file": "a.c", "line": 1})
    p = _offline_payload(monkeypatch, tmp_path)
    assert p["target"]["halted"] is None          # 三态：None = 压根没连
    assert p["target"]["state"] == "not-contacted"
    assert p["reset_cause"] is None
    assert p["stack"] == {"sp": None, "lr": None, "fault": None}


def test_offline_mode_echoes_which_elf_was_used(monkeypatch, tmp_path):
    """离线也要回显 ELF：cache/build 跨项目共享，答对了也不知道对的是谁。"""
    monkeypatch.setattr(ins, "_location",
                        lambda elf, pc, tc, w: {"pc": "0x08001D78", "function": "f",
                                                "file": "a.c", "line": 1})
    p = _offline_payload(monkeypatch, tmp_path)
    assert p["target"]["elf"].endswith("firmware.elf")
    assert p["target"]["elf_size"] > 0
    assert p["target"]["elf_mtime"]
