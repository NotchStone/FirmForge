"""Phase C 前置: CLI --json-mode resident-loop + stdout purity tests.

Covers:
  - json-mode result frames (detect/context) with {id, type, ok, value}
  - json-mode error frames (UNKNOWN_CMD / PROTOCOL)
  - exit frame terminates the loop
  - multiple commands in one session (serial dispatch)
  - T2 regression: cmd_flash auto-detect print must not pollute --json output
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
ENV = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}


def run_json_mode(frames: list[str]) -> subprocess.CompletedProcess:
    """Feed JSON frames to a --json-mode subprocess (harness: subprocess only)."""
    return subprocess.run(
        [sys.executable, "-m", "firmforge.adapters.cli", "--json-mode"],
        capture_output=True, encoding="utf-8", errors="replace",
        cwd=str(ROOT), timeout=120, env=ENV,
        input="\n".join(frames) + "\n",
    )


def parse_frames(stdout: str) -> list[dict]:
    """Parse every JSON line from stdout into frames."""
    return [json.loads(l) for l in stdout.strip().splitlines() if l.strip().startswith("{")]


class TestJsonModeFrames:
    def test_detect_result_frame(self):
        r = run_json_mode(['{"id":1,"cmd":"detect","args":{}}', '{"cmd":"exit"}'])
        assert r.returncode == 0, f"stderr: {r.stderr[-500:]}"
        frames = parse_frames(r.stdout)
        f = next(x for x in frames if x.get("id") == 1)
        assert f["type"] == "result"
        assert f["ok"] is True
        for key in ("board_id", "boards", "detected", "candidates"):
            assert key in f["value"], f"missing key {key}"

    def test_context_result_frame(self):
        r = run_json_mode(
            ['{"id":7,"cmd":"context","args":{"board":"arduino_328p"}}', '{"cmd":"exit"}'])
        assert r.returncode == 0
        frames = parse_frames(r.stdout)
        f = next(x for x in frames if x.get("id") == 7)
        assert f["type"] == "result" and f["ok"] is True
        assert f["value"]["board"] == "arduino_328p"
        assert "chip" in f["value"]

    def test_unknown_cmd_frame(self):
        r = run_json_mode(['{"id":2,"cmd":"no_such_cmd"}', '{"cmd":"exit"}'])
        f = next(x for x in parse_frames(r.stdout) if x.get("id") == 2)
        assert f["ok"] is False and f["code"] == "UNKNOWN_CMD"

    def test_protocol_error_frame(self):
        r = run_json_mode(["this is not json", '{"cmd":"exit"}'])
        f = parse_frames(r.stdout)[0]
        assert f["ok"] is False and f["code"] == "PROTOCOL"

    def test_exit_terminates(self):
        r = run_json_mode(['{"cmd":"exit"}'])
        assert r.returncode == 0
        assert r.stdout.strip() == ""  # exit 前无其他命令 → 无输出

    def test_multiple_commands_serial(self):
        r = run_json_mode([
            '{"id":1,"cmd":"context","args":{"board":"arduino_328p"}}',
            '{"id":2,"cmd":"badcmd"}',
            '{"cmd":"exit"}',
        ])
        frames = parse_frames(r.stdout)
        by_id = {f.get("id"): f for f in frames}
        assert by_id[1]["ok"] is True
        assert by_id[2]["ok"] is False and by_id[2]["code"] == "UNKNOWN_CMD"

    def test_build_requires_app_error_frame(self):
        r = run_json_mode(['{"id":5,"cmd":"build","args":{"board":"arduino_328p"}}', '{"cmd":"exit"}'])
        f = next(x for x in parse_frames(r.stdout) if x.get("id") == 5)
        assert f["ok"] is False
        assert "error" in f["value"]


class TestFlashJsonPurity:
    """`--json` 的 stdout 必须是单个 JSON 对象。

    旧实现会在 stdout 打 `Auto-detected firmware: ...`（靠 rglob 猜的），
    所以专门有一条测试盯着它。2026-10-27 改走流水线之后，那行探测彻底
    不存在了 —— 固件按 `--firmware` → state → 构建缓存解析，多份报错。
    但**约束没变**：stdout 只能是 JSON，所有进度都走 stderr。
    """

    @staticmethod
    def _patch(monkeypatch):
        from firmforge.providers import get_flash_provider

        class FakeFlasher:
            def detect_port(self):
                return "COM9"

            def flash(self, firmware):
                return SimpleNamespace(success=True, bytes_written=120,
                                       elapsed_ms=8, stderr="")

        monkeypatch.setattr(get_flash_provider, "__call__",
                            lambda self, *a, **kw: FakeFlasher(), raising=False)
        return FakeFlasher

    def _run(self, monkeypatch, tmp_path, json_mode: bool):
        from firmforge.adapters import cli
        import firmforge.providers as providers_pkg

        hexf = tmp_path / "firmware.hex"
        hexf.write_text(":00000001FF\n", encoding="utf-8")

        class FakeFlasher:
            def detect_port(self):
                return "COM9"

            def flash(self, firmware):
                return SimpleNamespace(success=True, bytes_written=120,
                                       elapsed_ms=8, stderr="")

        monkeypatch.setattr(providers_pkg, "get_flash_provider",
                            lambda platform, cfg: FakeFlasher())

        args = argparse.Namespace(
            command="flash", board="arduino_328p", firmware=str(hexf),
            app=None, json=json_mode, boards_dir=None,
            workspace=str(tmp_path),
        )
        if not json_mode:
            # 人类模式不重定向：让 capsys 能同时看到 stdout 与 stderr
            return cli.cmd_flash(args), ""
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cli.cmd_flash(args)
        return rc, buf.getvalue()

    def test_flash_json_stdout_is_pure_json(self, monkeypatch, tmp_path):
        rc, out = self._run(monkeypatch, tmp_path, json_mode=True)
        assert rc == 0
        payload = json.loads(out)          # 不能有半行人话混进来
        assert payload["success"] is True
        assert payload["bytes_written"] == 120

    def test_flash_human_mode_prints_result_to_stdout(self, monkeypatch, tmp_path, capsys):
        rc, _ = self._run(monkeypatch, tmp_path, json_mode=False)
        out, err = capsys.readouterr()
        assert rc == 0
        assert "[PASS] Stage 4 Flash" in out
        assert "[S4" in err, "进度行必须在 stderr，才能被管道之外的终端看到"

    def test_flash_no_board_pure_json(self):
        r = subprocess.run(
            [sys.executable, "-m", "firmforge.adapters.cli", "--json", "flash"],
            capture_output=True, text=True, cwd=str(ROOT), timeout=60, env=ENV,
        )
        assert r.returncode == 1
        payload = json.loads(r.stdout)  # must parse as pure JSON
        assert "error" in payload
