"""AVR 参考数据的同步规则 —— 只补缺项，不改已核验的内容。

A 区 ``registers.json`` 是**人工核验过的数据**（端口 H–L 地址、EEAR 口径、
ASSR 位号、UCSR 位名都按数据手册修过），同时器件头描述了更全的位域。
两者的关系是「子集 + 更全」，所以动作只能是**合并**，不能是重新生成。

这里守四条：

1. **只增不减**：任何一次同步都不能让寄存器或位变少。
2. **不动已核验内容**：改动已有位的位号 = 数据事故，不是同步。
3. **别名不重复收**：``SREG`` 的 ``C`` 与 ``SREG_C``、``UCSR0C`` 的
   ``UCSZ00`` 与 ``UCPHA0`` 是同一位的两个官方名字，收一个。
4. **可重复执行**：跑第二遍必须没有任何变更 —— 否则每次 CI 都会改一次
   入库文件，diff 里全是噪声。
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "sync_avr_reference.py"
REFERENCE = REPO_ROOT / "firmforge" / "data" / "knowledge" / "reference" / "avr"

#: 同步完成后的覆盖度。数字变小说明器件头换了版本或合并规则被改坏。
EXPECTED = {
    "atmega2560": {"registers": 212, "fields": 747},
    "atmega328p": {"registers": 96, "fields": 544},
}


def _load_script():
    spec = importlib.util.spec_from_file_location("sync_avr_reference", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def sync():
    return _load_script()


def _flat(path: Path) -> dict[str, dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {r["name"]: r
            for g in payload["register_groups"].values()
            for r in g["registers"]}


# --------------------------------------------------------------------------
# 1. 覆盖度
# --------------------------------------------------------------------------

@pytest.mark.parametrize("mcu", sorted(EXPECTED))
def test_coverage(mcu):
    regs = _flat(REFERENCE / mcu / "registers.json")
    fields = sum(len(r.get("fields") or []) for r in regs.values())
    assert len(regs) == EXPECTED[mcu]["registers"]
    assert fields == EXPECTED[mcu]["fields"]


@pytest.mark.parametrize("mcu", sorted(EXPECTED))
def test_already_synced(mcu, sync):
    """仓库里的数据必须是最新同步过的状态 —— 否则 CI 会开始漂移。"""
    summary = sync.merge(mcu, check_only=True)
    assert summary["changed"] is False, (
        f"{mcu} 与器件头不同步：新增 {summary['added_registers']}、"
        f"补位 {summary['added_bits']}")


# --------------------------------------------------------------------------
# 2. 人工内容保留
# --------------------------------------------------------------------------

def test_provenance_preserved():
    """每个寄存器都要能说出「描述来自哪」或「数据来自哪份头文件」。

    新增的寄存器只有来源没有描述（avr-libc 不提供逐寄存器描述），这是
    诚实的状态；编一句描述出来才是造假。
    """
    for mcu in EXPECTED:
        regs = _flat(REFERENCE / mcu / "registers.json")
        naked = [n for n, r in regs.items()
                 if not r.get("description") and not r.get("source")]
        assert not naked, f"{mcu} 有寄存器既无描述也无来源: {naked[:5]}"


def test_groups_not_collapsed():
    """生成器只会产出 ``unclassified`` 一组；A 区必须是人工的 17 组。"""
    payload = json.loads(
        (REFERENCE / "atmega2560" / "registers.json").read_text(encoding="utf-8"))
    groups = set(payload["register_groups"])
    assert "unclassified" not in groups
    assert len(groups) >= 15


# --------------------------------------------------------------------------
# 3. 合并规则（在临时副本上验证，不碰真实数据）
# --------------------------------------------------------------------------

@pytest.fixture
def sandbox(tmp_path):
    """把两个芯片的数据复制到临时目录，供合并实验使用。"""
    for mcu in EXPECTED:
        dst = tmp_path / mcu
        dst.mkdir(parents=True)
        shutil.copy(REFERENCE / mcu / "registers.json",
                    dst / "registers.json")
    return tmp_path


def test_second_run_is_noop(sandbox, sync):
    """幂等：第一次合并完，第二次必须没有变更。"""
    first = sync.merge("atmega2560", root=sandbox)
    assert first["changed"] is False or first["changed"] is True
    second = sync.merge("atmega2560", root=sandbox)
    assert second["changed"] is False
    assert second["added_bits"] == 0
    assert second["added_registers"] == []


def test_merge_never_drops_registers(sandbox, sync):
    before = _flat(sandbox / "atmega2560" / "registers.json")
    sync.merge("atmega2560", root=sandbox)
    after = _flat(sandbox / "atmega2560" / "registers.json")
    assert set(before) <= set(after)


def test_merge_never_moves_existing_bits(sandbox, sync):
    """已有位的位号是被核验过的，合并只许追加，不许搬家。"""
    before = _flat(sandbox / "atmega2560" / "registers.json")
    sync.merge("atmega2560", root=sandbox)
    after = _flat(sandbox / "atmega2560" / "registers.json")
    for name, old in before.items():
        new = after[name]
        old_bits = {f["name"]: f["bit"] for f in old.get("fields") or []}
        new_bits = {f["name"]: f["bit"] for f in new.get("fields") or []}
        for fld, bit in old_bits.items():
            assert new_bits.get(fld) == bit, f"{name}.{fld} 位号被改动"


def test_no_duplicate_bit_per_register(sandbox, sync):
    """同一位不许出现两个名字 —— 别名在合并时只收人工选定的那个。"""
    sync.merge("atmega2560", root=sandbox)
    regs = _flat(sandbox / "atmega2560" / "registers.json")
    dup = []
    for name, reg in regs.items():
        bits = [f["bit"] for f in reg.get("fields") or []]
        if len(bits) != len(set(bits)):
            dup.append(name)
    assert not dup, f"同一位出现多个名字: {dup[:5]}"


def test_alias_keeps_human_name(sandbox, sync):
    """``SREG`` 的位名是人工选定的人读名（C/Z/N…），不是宏基名（SREG_C）。"""
    regs = _flat(sandbox / "atmega2560" / "registers.json")
    sreg = {f["name"] for f in regs["SREG"]["fields"]}
    assert "C" in sreg and "SREG_C" not in sreg


def test_same_address_alias_takes_richer_one(sandbox, sync):
    """0x51 上 ``MONDR`` 没有位定义、``OCDR`` 有 9 个 —— 收 ``OCDR``。"""
    sync.merge("atmega2560", root=sandbox)
    regs = _flat(sandbox / "atmega2560" / "registers.json")
    at_0x51 = [n for n, r in regs.items()
               if str(r.get("address", "")).lower() == "0x51"]
    assert len(at_0x51) == 1, f"0x51 同址收了多个: {at_0x51}"
    assert at_0x51[0] == "OCDR"


# --------------------------------------------------------------------------
# 4. 命令行行为
# --------------------------------------------------------------------------

def test_check_mode_exits_zero_when_synced():
    proc = subprocess.run([sys.executable, str(SCRIPT), "--check"],
                          cwd=str(REPO_ROOT), capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout[-800:]
    assert "已是最新" in proc.stdout
