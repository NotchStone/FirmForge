"""`ff build --apps` 批量入口的解析与参数接线。

批量模式的存在理由是可量化的：这台机器起一个 Python 进程要 ~1.9 s
（真正导入 firmforge 只占 0.25 s），73 个用例光启动就 2.3 分钟。
批量把进程启动收成一次，编译仍是一例一次。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from firmforge.adapters.cli import _parse_app_list, setup_argument_parser


class TestParseAppList:
    def test_comma_separated_keeps_existing_dirs(self, tmp_path: Path):
        a = tmp_path / "a"
        b = tmp_path / "b"
        a.mkdir()
        b.mkdir()
        got = _parse_app_list(f"{a},{b}")
        assert got == [str(a), str(b)]

    def test_missing_dir_is_dropped_not_fatal(self, tmp_path: Path):
        a = tmp_path / "a"
        a.mkdir()
        got = _parse_app_list(f"{a},{tmp_path / 'nope'}")
        assert got == [str(a)]

    def test_file_mode_skips_blank_and_comment_lines(self, tmp_path: Path):
        a = tmp_path / "a"
        b = tmp_path / "b"
        a.mkdir()
        b.mkdir()
        listing = tmp_path / "apps.txt"
        listing.write_text(f"# 注释行\n{a}\n\n{b}\n", encoding="utf-8")
        assert _parse_app_list(f"@{listing}") == [str(a), str(b)]

    def test_missing_list_file_returns_empty(self, tmp_path: Path):
        assert _parse_app_list(f"@{tmp_path / 'absent.txt'}") == []

    def test_blank_spec_returns_empty(self):
        assert _parse_app_list("   ") == []


class TestParserWiring:
    def test_build_accepts_apps_flag(self):
        parser = setup_argument_parser()
        args = parser.parse_args(["build", "arduino_mega", "--apps", "x,y"])
        assert args.apps == "x,y"

    def test_app_and_apps_are_independent(self):
        parser = setup_argument_parser()
        args = parser.parse_args(["build", "arduino_mega", "--app", "only-one"])
        assert args.app is not None
        assert getattr(args, "apps", None) in (None, "")

    def test_json_works_before_and_after_subcommand(self):
        """`--json` 在两个位置都必须生效。

        历史：原先只有根解析器认 `--json`，`ff build ... --json` 会被判为
        `unrecognized arguments`（退出码 2、stdout 空白）—— 批量入口踩过这个坑，
        当时的处置是"把参数挪到前面"，于是这条约束被固化成了测试。
        但把缺陷写成契约是错的：人的第一直觉就是写在子命令后面，写在后面还静默
        失败更像"命令没输出"。现在两个位置都认（子命令那份用 `SUPPRESS` 默认值，
        不覆盖根上的取值）。
        """
        parser = setup_argument_parser()
        assert parser.parse_args(["--json", "build", "arduino_mega", "--apps", "x"]).json is True
        assert parser.parse_args(["build", "arduino_mega", "--apps", "x", "--json"]).json is True
        # 不写就是 False，不能因为子命令挂了 flag 而变成 True
        assert parser.parse_args(["build", "arduino_mega", "--apps", "x"]).json is False
