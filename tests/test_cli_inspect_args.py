"""`ff inspect` 的命令行参数解析。

地址写法看着是小事，但 `--pc 800` 按十进制读成 800 而不是 0x800 时，
addr2line 会给出一个**另一处**的合法行号 —— 输出照常、退出码 0，
只有对着反汇编看才会发现对不上。所以「一律十六进制」必须锁住。
"""

from __future__ import annotations

import argparse

import pytest

from firmforge.adapters import cli


@pytest.mark.parametrize("text,expected", [
    ("0x08001D78", 0x08001D78),
    ("0X08001D78", 0x08001D78),
    ("08001D78", 0x08001D78),
    ("0x0800_1D78", 0x08001D78),
    ("0", 0),
])
def test_pc_accepts_common_address_forms(text, expected):
    assert cli._parse_pc(text) == expected


def test_pc_without_prefix_is_still_hex():
    """`--pc 800` 必须是 0x800。地址没有十进制写法，按十进制读会静默错位。"""
    assert cli._parse_pc("800") == 0x800


def test_pc_rejects_non_hex():
    with pytest.raises(argparse.ArgumentTypeError):
        cli._parse_pc("zz")


def test_pc_error_message_shows_the_expected_form():
    """报错要给出正确写法 —— 只说"无效"等于让人去猜。"""
    with pytest.raises(argparse.ArgumentTypeError) as ei:
        cli._parse_pc("0xZZ")
    assert "0x08001D78" in str(ei.value)


def test_inspect_parser_has_app_and_pc():
    """`--app` / `--pc` 缺一个，对应的能力就等于没做（用户只能回到 --elf + 人工推算）。"""
    parser = cli.setup_argument_parser()
    # argparse 的子解析器藏在 _SubParsersAction 里，没有公开的查询接口
    subs = [a for a in parser._actions
            if isinstance(a, argparse._SubParsersAction)][0]
    ins = subs.choices["inspect"]
    opts = {o for a in ins._actions for o in a.option_strings}
    assert "--app" in opts
    assert "--pc" in opts
