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

    def test_json_is_global_not_per_subcommand(self):
        """--json 必须放在子命令之前；放到后面会被判为未知参数。

        批量入口就是踩在这个坑上：写成 `ff build ... --json` 直接
        `unrecognized arguments`，而且退出码是 2、没有任何可用输出。
        """
        parser = setup_argument_parser()
        assert parser.parse_args(["--json", "build", "arduino_mega", "--apps", "x"]).json is True
        with pytest.raises(SystemExit):
            parser.parse_args(["build", "arduino_mega", "--apps", "x", "--json"])
