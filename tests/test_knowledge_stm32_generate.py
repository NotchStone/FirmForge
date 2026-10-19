"""STM32 知识库**生成物**（B 区）的落地校验。

与 `test_knowledge_stm32.py` 的分工：

* 那边测**比对器**（SVD ↔ 器件头谁对谁错、缺陷表是否失效）；
* 这边测**生成物**（落盘的数据是否真按裁定结果写、lock 指纹是否自洽）。

为什么单列：比对通过 ≠ 数据可用。生成器可能把 SVD 原名原样写出去
（源码里根本不会出现 `MODE0`），也可能照抄 SVD 的错误地址
（`PRAR_PRG2` 差 0x100）。这些错误在比对报告里都是「已裁定」，
只有对着产物才能发现。

B 区产物不存在时整组 skip —— 干净环境不会因此失败。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from firmforge.knowledge.extractors import stm32_registers as gen

REG_DIR = (Path.home() / ".firmforge" / "cache" / "knowledge"
           / "stm32" / "stm32h743zit6")
REG_PATH = REG_DIR / "registers.json"
LOCK_PATH = REG_DIR / "lock.json"
SCHEMA = (Path(__file__).resolve().parents[1] / "firmforge" / "data"
          / "knowledge" / "schema" / "registers.schema.json")


@pytest.fixture(scope="module")
def data() -> dict:
    if not REG_PATH.is_file():
        pytest.skip("B 区无生成物；先跑 python -m "
                    "firmforge.knowledge.extractors.stm32_registers")
    return json.loads(REG_PATH.read_text(encoding="utf-8"))


def _reg(data: dict, peripheral: str, register: str) -> dict:
    for row in data["register_groups"][peripheral]["registers"]:
        if row["name"] == register:
            return row
    raise AssertionError(f"{peripheral}.{register} 不在数据里")


def _field(register: dict, name: str) -> dict:
    for fld in register.get("fields", ()):
        if fld["name"] == name:
            return fld
    raise AssertionError(f"{register['name']} 里没有位域 {name}")


# --------------------------------------------------------------------------
# 结构合法
# --------------------------------------------------------------------------


def test_generated_file_validates_against_schema(data):
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(data)


def test_schema_allows_the_alignment_provenance_fields(data):
    """`svd_name` / `name_source` / `bit_source` 必须被 schema 显式允许。

    这几个不是装饰：没有 `svd_name` 就无法回溯两边的命名口径，
    没有 `bit_source` 就分不清某个位号是 SVD 说的还是器件头说的。
    """
    props = json.loads(SCHEMA.read_text(encoding="utf-8"))["$defs"]["field"]
    for key in ("svd_name", "name_source", "bit_source",
                "header_bit", "bit_conflict"):
        assert key in props["properties"], f"schema 未允许 {key}"


# --------------------------------------------------------------------------
# 名字：必须是源码里能出现的宏基名
# --------------------------------------------------------------------------


def test_gpio_mode_fields_use_header_macro_names(data):
    """SVD 叫 `MODE0`，源码里是 `GPIO_MODER_MODER0_Pos`。

    数据里必须存 `GPIO_MODER_MODER0`（宏基名），SVD 名留 `svd_name`。
    这条曾经漏过：生成器只做 SVD 解析时，GPIO 全线位域名对不上源码。
    """
    reg = _reg(data, "GPIOA", "MODER")
    field = _field(reg, "GPIO_MODER_MODER0")
    assert field["svd_name"] == "MODE0"
    assert field["bit"] == 0
    assert field.get("bit_width") == 2


def test_pupdr_uses_the_full_macro_name_as_is(data):
    """SVD `PUPD0` 与器件头 `GPIO_PUPDR_PUPD0` 尾段一致，只需补前缀。

    与上一条对照：GPIO 里只有 MODER 需要 `MODE0 → MODER0` 的兜底，
    PUPDR / OSPEEDR 的名字本来就对。`name` 一律存**完整宏基名**，
    `svd_name` 存 SVD 原名 —— 两者不同是常态（差的是外设/寄存器前缀）。
    """
    field = _field(_reg(data, "GPIOA", "PUPDR"), "GPIO_PUPDR_PUPD0")
    assert field["svd_name"] == "PUPD0"
    assert field["bit"] == 0


def test_no_field_keeps_an_svd_only_name_when_a_macro_exists(data):
    """凡命中了器件头宏的位域，name 必须不是 SVD 原名。

    未命中的（器件头没建模、或拼法差异超出兜底范围）保留原名是允许的，
    但必须没有 `svd_name` —— 有 `svd_name` 就说明改过名，两者矛盾。
    """
    aligned = renamed = 0
    for group in data["register_groups"].values():
        for reg in group["registers"]:
            for fld in reg.get("fields", ()):
                if "svd_name" in fld:
                    renamed += 1
                    assert fld["name"] != fld["svd_name"]
                aligned += 1
    assert renamed > 8000, f"改名数量异常少（{renamed}），对齐可能没生效"
    assert renamed < aligned


# --------------------------------------------------------------------------
# 位号：按裁定表定夺，不静默选一边
# --------------------------------------------------------------------------


def test_bdma_bit_shift_is_applied(data):
    """BDMA 的 ISR/IFCR 位号整体偏 4（SVD 错）—— 数据必须取器件头值。"""
    field = _field(_reg(data, "BDMA", "ISR"), "BDMA_ISR_GIF1")
    assert field["bit"] == 4
    assert field["bit_source"] == "header"


def test_header_side_defect_keeps_svd_bit(data):
    """SYSCFG.UR3.BOOT_ADD1 是**器件头**写错（0 而非 16），数据取 SVD 值。

    这条与上一条是同一个机制的两个方向：裁定表判谁错就取另一边，
    不能一律「以器件头为准」。
    """
    field = _field(_reg(data, "SYSCFG", "UR3"), "SYSCFG_UR3_BOOT_ADD1")
    assert field["bit"] == 16
    assert field["bit_source"] == "svd"


def test_adc_awd_channel_bit_is_corrected(data):
    """ADC1/2/3 的 AWDxCR.AWDxCH 在 SVD 里写成 bit 1，器件头是 bit 0。"""
    for adc in ("ADC1", "ADC2", "ADC3"):
        field = _field(_reg(data, adc, "AWD3CR"), "ADC_AWD3CR_AWD3CH")
        assert field["bit"] == 0
        assert field["bit_source"] == "header"


def test_only_one_unadjudicated_bit_conflict(data):
    """未裁定冲突只允许 1 条（Ethernet RXCHCNT，等手册确认）。

    这条是**上限不是目标**：新增任何未裁定冲突都说明裁定表漏了，
    应当先取证登记，而不是把断言放宽。
    """
    align = data["_generator"]["header"]["alignment"]
    assert align["bits_conflict"] == 1
    assert len(align["conflicts"]) == 1
    assert "MACHWF2R.RXCHCNT" in align["conflicts"][0]


# --------------------------------------------------------------------------
# 地址：漏保留区导致的整体偏移必须修
# --------------------------------------------------------------------------


def test_flash_prar_program_registers_are_not_aliased(data):
    """SVD 曾把 PRAR_PRG2 写成与 PRAR_PRG1 同址（漏了 0x100 的步进）。

    数据里两者的地址必须相差 0x100 —— 同址会让 S2 把两个编程寄存器
    认成一个（首轮 check_knowledge 就是这么报出来的）。
    """
    prg1 = int(_reg(data, "Flash", "PRAR_PRG1")["address"], 16)
    prg2 = int(_reg(data, "Flash", "PRAR_PRG2")["address"], 16)
    assert prg2 - prg1 == 0x100


def test_no_unadjudicated_register_address_conflicts(data):
    align = data["_generator"]["header"]["alignment"]
    assert align["registers_conflict"] == 0
    assert align["register_conflicts"] == []


def test_address_corrections_are_recorded_with_provenance(data):
    """凡地址经裁定修正的寄存器，必须带 `address_source: "header"`。

    只改值不留痕，下次比对会以为生成器算错；`registers_corrected`
    与实际带标记的条目数也必须一致。
    """
    marked = [r for group in data["register_groups"].values()
              for r in group["registers"]
              if r.get("address_source") == "header"]
    align = data["_generator"]["header"]["alignment"]
    assert len(marked) == align["registers_corrected"]
    assert len(marked) > 0


# --------------------------------------------------------------------------
# lock.json
# --------------------------------------------------------------------------


def test_lock_fingerprints_are_self_consistent():
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert lock["generator_version"] == gen.EXTRACTOR_VERSION
    assert lock["output"] == REG_PATH.name
    assert lock["output_sha256"] == gen.sha256_of(REG_PATH)
    assert lock["inputs"], "lock 必须记输入指纹"
    for raw, want in lock["inputs"].items():
        path = Path(raw.replace("~", str(Path.home()), 1))
        assert path.is_file(), f"lock 指向的输入不存在: {raw}"
        assert gen.sha256_of(path) == want, f"输入指纹不符: {raw}"


def test_lock_counts_match_the_payload(data):
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert lock["counts"] == data["_generator"]["counts"]


# --------------------------------------------------------------------------
# 生成器本身（不依赖 B 区产物）
# --------------------------------------------------------------------------


def test_generator_is_reproducible_on_real_sources(tmp_path):
    """同一对源文件重跑，计数与对齐结论必须一致。

    `generated_at` / `elapsed_ms` 每次不同，所以不比整文件哈希 ——
    比**结论**（计数、裁定次数、未裁定条目）。这些一变就说明生成器
    的行为漂了。
    """
    from firmforge.knowledge.parity import (
        STM32_DEVICES, default_cmsis_include, find_svd)

    svd_name, header_name = STM32_DEVICES["stm32h743zit6"]
    svd = find_svd(svd_name, Path(__file__).resolve().parents[1])
    header = default_cmsis_include() / header_name
    if svd is None or not header.is_file():
        pytest.skip("源文件不全（SVD 或器件头）")

    out = tmp_path / "registers.json"
    result = gen.extract_stm32_registers(svd, mcu="stm32h743zit6",
                                         header_path=header)
    gen.write_registers(result, out)

    align = result["_generator"]["header"]["alignment"]
    assert result["_generator"]["counts"]["peripherals"] == 128
    assert align["peripherals_mapped"] == 115
    assert align["fields_aligned"] > 8000
    assert align["registers_conflict"] == 0
    assert align["bits_conflict"] == 1

    lock = gen.build_lock(result, output_path=out, inputs=[svd, header],
                          params={"mcu": "stm32h743zit6"})
    assert lock["output_sha256"] == gen.sha256_of(out)
    assert len(lock["inputs"]) == 2
