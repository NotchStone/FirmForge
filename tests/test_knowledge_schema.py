"""知识库 schema 一致性测试。

这些测试守的是一种特定的失败模式：**静默失败**。
`knowledge_base.py` 用 `.get(...)` 宽松解析，格式写错不抛异常，只返回空 ——
S2 的寄存器/引脚审查会因此全部变成漏检，而流水线仍然报 PASS。

历史上真实发生过（2026-09 整改时发现）：
  - `atmega328p/pins.json` 的 `board` 写的是 "arduino_uno"，
    而 board_id 是 "arduino_328p" → `get_pin_map("arduino_328p")` 返回空。
  - 同一文件的 `port` 写 "PORTD"，而 confidence_scorer 用 `PORT{port}`
    拼寄存器名 → 会拼出 "PORTPORTD"。

所以这里的断言不是形式主义，每一条都对应一个曾经真实的缺陷。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "firmforge" / "data"
REF = DATA / "knowledge" / "reference"
SCHEMA_DIR = DATA / "knowledge" / "schema"

jsonschema = pytest.importorskip(
    "jsonschema", reason="jsonschema required (run with the mcu_agent venv)")


def _documents() -> list[Path]:
    return sorted(REF.rglob("*.json")) if REF.is_dir() else []


def _ids(path: Path) -> str:
    try:
        return path.relative_to(REF).as_posix()
    except ValueError:
        return str(path)


# --------------------------------------------------------------------------
# Schema 一致性
# --------------------------------------------------------------------------

@pytest.mark.parametrize("doc", _documents(), ids=_ids)
def test_document_conforms_to_declared_schema(doc: Path) -> None:
    """每个数据文件都必须通过它自己 $schema 指向的 schema。"""
    payload = json.loads(doc.read_text(encoding="utf-8"))
    ref = payload.get("$schema", "")
    assert ref.startswith("knowledge/schema/"), (
        f"{doc.name}: $schema must point at a project schema, got {ref!r}")

    schema_path = DATA / ref
    assert schema_path.exists(), f"{doc.name}: declared schema {ref} does not exist"

    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(payload)


def test_every_schema_exists_and_is_valid() -> None:
    """schema 目录下每个文件都必须是合法的 draft 2020-12 schema。"""
    schemas = sorted(SCHEMA_DIR.glob("*.schema.json"))
    assert schemas, "no schemas found — the whole contract layer is missing"
    for path in schemas:
        body = json.loads(path.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(body)


# --------------------------------------------------------------------------
# 跨文件语义（JSON Schema 表达不了，但会静默失败）
# --------------------------------------------------------------------------

def test_pins_board_matches_boards_directory() -> None:
    """`board` 必须与 firmforge/data/boards/<board>/ 目录名一致。

    不一致不会报错 —— `get_pin_map(board_id)` 只会静默返回空。
    """
    boards_dir = DATA / "boards"
    known = {p.name for p in boards_dir.iterdir() if p.is_dir()}
    assert known, f"no board definitions found under {boards_dir}"

    offenders = []
    for doc in REF.rglob("pins.json"):
        payload = json.loads(doc.read_text(encoding="utf-8"))
        board = payload.get("board")
        if board not in known:
            offenders.append(f"{_ids(doc)}: board={board!r}")
    assert not offenders, (
        f"pins.json board must be a real board_id {sorted(known)}; "
        f"get_pin_map() silently returns empty otherwise. Got: {offenders}")


def test_mcu_agrees_across_files_in_same_chip_dir() -> None:
    """同一芯片目录下 registers.json 与 pins.json 的 mcu 必须一致。"""
    mismatches = []
    for chip_dir in sorted(p for p in REF.iterdir() if p.is_dir()):
        seen: dict[str, str] = {}
        for name in ("registers.json", "pins.json"):
            path = chip_dir / name
            if path.exists():
                seen[name] = json.loads(path.read_text(encoding="utf-8")).get("mcu", "")
        if len(set(seen.values())) > 1:
            mismatches.append(f"{chip_dir.name}: {seen}")
    assert not mismatches, f"mcu differs between files: {mismatches}"


# --------------------------------------------------------------------------
# 形状断言 —— 对应 confidence_scorer 与 knowledge_base 的解析假设
# --------------------------------------------------------------------------

def test_pins_is_a_list_and_port_is_a_single_letter() -> None:
    """`pins` 必须是 list，`port` 必须是单字母。

    confidence_scorer.py 用 `PORT{port}` 拼寄存器名 —— 若 port 是 "PORTD"，
    会拼出 "PORTPORTD" 并写进给 Agent 的置信度报告。
    """
    problems = []
    for doc in REF.rglob("pins.json"):
        payload = json.loads(doc.read_text(encoding="utf-8"))
        pins = payload.get("pins")
        if not isinstance(pins, list):
            problems.append(f"{_ids(doc)}: pins is {type(pins).__name__}, expected list")
            continue
        for pin in pins:
            port = pin.get("port", "")
            if not (isinstance(port, str) and len(port) == 1 and port.isupper()):
                problems.append(
                    f"{_ids(doc)} pin {pin.get('arduino_pin')}: port={port!r}")
    assert not problems, f"port must be a single uppercase letter: {problems}"


def test_arduino_pin_values_are_unique_and_dense() -> None:
    """引脚号必须唯一，且覆盖 0..n-1（knowledge_base 按号建索引）。"""
    for doc in REF.rglob("pins.json"):
        payload = json.loads(doc.read_text(encoding="utf-8"))
        nums = [p["arduino_pin"] for p in payload["pins"]]
        assert len(nums) == len(set(nums)), f"{_ids(doc)}: duplicate arduino_pin"
        assert sorted(nums) == list(range(len(nums))), (
            f"{_ids(doc)}: arduino_pin must cover 0..{len(nums) - 1} without gaps, "
            f"got {sorted(nums)[:5]}...{sorted(nums)[-3:]}")


def test_register_addresses_are_hex_strings() -> None:
    """地址必须是 '0x..' 字符串 —— 整数会丢 @ 形式与内存映射的区别。"""
    for doc in REF.rglob("registers.json"):
        payload = json.loads(doc.read_text(encoding="utf-8"))
        for group in payload["register_groups"].values():
            for reg in group["registers"]:
                addr = reg.get("address", "")
                assert isinstance(addr, str) and addr.startswith("0x"), (
                    f"{_ids(doc)} {reg.get('name')}: address={addr!r} "
                    "must be a '0x..' string")
