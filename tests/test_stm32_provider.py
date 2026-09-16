"""STM32 路线（GC-H743）提供者层测试。

设计原则：**不依赖厂商 SDK 是否已下载**。SDK 缺失时跳过依赖它的用例，
其余用例（声明一致性、命令行拼装、诊断解析）在任何环境都跑。

真正需要 SDK 的部分是"能不能编出固件"，那属于集成测试，不在这一层。
这一层钉住的是三件容易悄悄坏掉的事：
  1. `board.yaml` 的声明内部自洽（HAL 模块清单 ↔ hal_conf.h ↔ 链接脚本）
  2. 提供者注册表能把 `platform: stm32` 路由到 stm32 实现
  3. 命令行拼装正确 —— 尤其 OpenOCD 拿不到 shell 引号，路径要自己加花括号
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from firmforge.core.resources import boards_dir
from firmforge.providers import get_build_provider, get_flash_provider
from firmforge.providers.gcc_diagnostics import parse_gcc_diagnostics
from firmforge.providers.stm32.build import Stm32BuildProvider, hal_module_guard
from firmforge.providers.stm32.flash import Stm32FlashProvider
from firmforge.providers.stm32.toolchain import (
    Stm32Toolchain,
    find_arm_gcc,
    find_openocd,
    resolve_toolchain,
)

BOARD_ID = "gc_h743"


@pytest.fixture(scope="module")
def board_cfg() -> dict:
    raw = yaml.safe_load(
        (boards_dir() / BOARD_ID / "board.yaml").read_text(encoding="utf-8"))
    raw["board_id"] = BOARD_ID
    return raw


def board_dir() -> Path:
    """板卡目录（`data/boards/gc_h743/`）。"""
    return boards_dir() / BOARD_ID


# --------------------------------------------------------------------------
# 1. 声明自洽
# --------------------------------------------------------------------------


def test_board_declares_stm32_platform(board_cfg: dict) -> None:
    assert board_cfg["platform"] == "stm32"
    assert board_cfg["mcu"]["chip"] == "STM32H743ZIT6"


def test_board_has_build_and_flash_sections(board_cfg: dict) -> None:
    """`构建参数是数据` —— 缺段就说明参数被硬编码进了代码。"""
    build = board_cfg.get("build", {})
    for key in ("sdk", "defines", "startup", "system",
                "linker_script", "hal_conf", "hal_modules"):
        assert key in build, f"board.yaml 缺少 build.{key}"
    flash = board_cfg.get("flash", {})
    for key in ("interface_cfg", "target_cfg"):
        assert key in flash, f"board.yaml 缺少 flash.{key}"


def test_hal_modules_match_hal_conf_enables(board_cfg: dict) -> None:
    """`hal_modules` 与 hal_conf.h 的 `HAL_<MOD>_MODULE_ENABLED` 必须一致。

    不一致的后果不是编译报错，而是**链接期缺少某个 HAL 函数**，或者反过来
    编进了一堆用不到的模块 —— 都是难归因的错。
    """
    hal_conf = board_dir() / board_cfg["build"]["hal_conf"]
    if not hal_conf.is_file():
        pytest.skip("板级 hal_conf.h 尚未落地")
    text = hal_conf.read_text(encoding="utf-8", errors="replace")
    enabled = set(re.findall(r"^\s*#define\s+HAL_([A-Z0-9_]+)_MODULE_ENABLED",
                             text, re.MULTILINE))
    # `HAL_MODULE_ENABLED`（无中间段）守着 stm32h7xx_hal.c 本身
    assert "HAL_MODULE_ENABLED" in text, "hal_conf.h 缺 HAL_MODULE_ENABLED"
    declared = {hal_module_guard(str(m))
                for m in board_cfg["build"]["hal_modules"]}
    missing = declared - enabled
    assert not missing, f"这些模块在 hal_conf.h 里没启用: {sorted(missing)}"


def test_linker_memory_regions_match_board_declaration(board_cfg: dict) -> None:
    """链接脚本的 ORIGIN/LENGTH 必须与 board.yaml::memories 逐条一致。

    两边是同一份硬件事实的两次书写 —— 一旦分叉，`board.yaml` 会拿错误的
    地址去校验寄存器访问，而这种错不会自己暴露。
    """
    ld = board_dir() / board_cfg["build"]["linker_script"]
    if not ld.is_file():
        pytest.skip("板级链接脚本尚未落地")
    text = ld.read_text(encoding="utf-8", errors="replace")
    body = re.search(r"MEMORY\s*\{(.*?)\}", text, re.DOTALL)
    assert body, "链接脚本里找不到 MEMORY 段"
    regions = {
        m.group(1): (int(m.group(2), 16), m.group(3))
        for m in re.finditer(r"(\w+)\s*\([^)]*\)\s*:\s*ORIGIN\s*=\s*(0x[0-9A-Fa-f]+)"
                             r"\s*,\s*LENGTH\s*=\s*([0-9]+K?)",
                             body.group(1))
    }
    for mem in board_cfg.get("memories", []):
        name = mem["name"]
        if name == "BKPSRAM":
            continue        # 备份域 SRAM 由 HAL 用指针访问，不进链接布局
        assert name in regions, f"链接脚本缺少内存区 {name}"
        origin, declared = regions[name]
        assert origin == int(mem["start"], 16), \
            f"{name} 起始地址不一致: ld={hex(origin)} board.yaml={mem['start']}"
        want_kb = int(str(mem["size"]).split()[0])
        got_kb = int(declared.rstrip("K")) if declared.endswith("K") else \
            int(declared) // 1024
        assert got_kb == want_kb, \
            f"{name} 容量不一致: ld={got_kb}K board.yaml={want_kb}K"


def test_board_dir_has_no_stray_generated_files() -> None:
    """板卡目录里不应出现构建产物（R2：派生物不得物理位于 A 区）。"""
    stray = [p.name for p in board_dir().rglob("*")
             if p.is_file() and p.suffix in (".o", ".elf", ".hex", ".bin", ".map")]
    assert not stray, f"板卡目录出现构建产物: {stray}"


# --------------------------------------------------------------------------
# 2. 注册表路由
# --------------------------------------------------------------------------


def test_registry_routes_stm32(board_cfg: dict) -> None:
    builder = get_build_provider("stm32", board_cfg)
    flasher = get_flash_provider("stm32", board_cfg)
    assert isinstance(builder, Stm32BuildProvider)
    assert isinstance(flasher, Stm32FlashProvider)


def test_unknown_platform_still_rejected(board_cfg: dict) -> None:
    with pytest.raises(ValueError):
        get_build_provider("no_such_platform", board_cfg)


# --------------------------------------------------------------------------
# 3. 工具链探测（不抛异常是契约）
# --------------------------------------------------------------------------


def test_toolchain_probe_never_raises() -> None:
    tc = resolve_toolchain()
    assert isinstance(tc, Stm32Toolchain)
    assert isinstance(tc.problems(), list)


def test_toolchain_missing_reports_actionable_text() -> None:
    """空工具链的 problems() 必须说清"装什么、放哪里"，而不是只报 False。"""
    empty = Stm32Toolchain()
    assert not empty.compiler_ready
    assert not empty.flasher_ready
    issues = empty.problems()
    # 2 条而不是 3 条：openocd 整个没找到时只说一次，
    # 不会再加一条"scripts 目录没找到"（那是找到但布局不对时才报的）
    assert len(issues) == 2
    assert any("arm-none-eabi-gcc" in i for i in issues)
    assert any("openocd" in i for i in issues)


def test_toolchain_reports_scripts_gap_separately() -> None:
    """openocd 在但 scripts 不在 —— 这是**另一种**故障，要分开报。"""
    half = Stm32Toolchain(openocd="/usr/bin/openocd", openocd_scripts=None)
    issues = half.problems()
    assert len(issues) == 2
    assert any("scripts" in i for i in issues)


def test_openocd_scripts_dir_is_resolved_when_present() -> None:
    """xPack 布局下 scripts 在 <root>/openocd/scripts，不是 <root>/scripts。"""
    exe, _bin_dir, scripts = find_openocd()
    if not exe:
        pytest.skip("本机未安装 openocd")
    assert scripts, "openocd 找到了但 scripts 未解析 —— scripts_dir_candidates 需更新"
    assert Path(scripts).is_dir()


def test_arm_gcc_bin_dir_contains_gcc() -> None:
    gcc, bin_dir = find_arm_gcc()
    if not gcc:
        pytest.skip("本机未安装 arm-none-eabi-gcc")
    assert Path(gcc).is_file()
    if bin_dir:
        assert (Path(bin_dir) / "arm-none-eabi-objcopy").is_file() or \
               (Path(bin_dir) / "arm-none-eabi-objcopy.exe").is_file()


# --------------------------------------------------------------------------
# 4. 源码收集
# --------------------------------------------------------------------------


def test_collect_sources_excludes_output_dir(tmp_path: Path) -> None:
    src = tmp_path / "app"
    src.mkdir()
    (src / "main.c").write_text("int main(void){return 0;}", encoding="utf-8")
    out = src / "build_out"
    out.mkdir()
    (out / "leftover.c").write_text("// generated", encoding="utf-8")

    found = Stm32BuildProvider._collect_sources(src, out)
    names = {Path(f).name for f in found}
    assert names == {"main.c"}


def test_collect_sources_picks_asm_and_cpp(tmp_path: Path) -> None:
    src = tmp_path / "app"
    src.mkdir()
    for name in ("a.c", "b.cpp", "c.S", "d.txt"):
        (src / name).write_text("", encoding="utf-8")
    found = {Path(f).name for f in Stm32BuildProvider._collect_sources(src, tmp_path / "o")}
    assert found == {"a.c", "b.cpp", "c.S"}


# --------------------------------------------------------------------------
# 5. 命令行拼装
# --------------------------------------------------------------------------


def test_build_preflight_fails_fast_without_sources(board_cfg: dict,
                                                   tmp_path: Path) -> None:
    """空源码目录 → 失败，且错误信息指出目录。"""
    builder = Stm32BuildProvider(board_cfg)
    empty = tmp_path / "empty"
    empty.mkdir()
    result = builder.build(str(empty))
    assert not result.success
    # 工具链或 SDK 缺失时会先在这里拦下 —— 两种情况都必须是可读的说明
    assert result.stderr
    assert result.errors


def test_openocd_command_quotes_the_firmware_path(board_cfg: dict,
                                                 tmp_path: Path) -> None:
    """OpenOCD 的 `-c` 不过 shell，路径含空格必须自己加花括号。"""
    fw = tmp_path / "my app" / "firmware.hex"
    fw.parent.mkdir(parents=True)
    fw.write_text(":00000001FF", encoding="utf-8")
    flasher = Stm32FlashProvider(board_cfg)
    cmd = flasher._openocd_command("flash", str(fw))
    joined = " ".join(cmd)
    assert "{/" in joined or "{C:" in joined or joined.count("{") >= 1
    assert "}" in joined
    assert "program" in joined and "verify" in joined and "exit" in joined
    assert "-s" in cmd


def test_openocd_verify_command_uses_verify_image(board_cfg: dict,
                                                  tmp_path: Path) -> None:
    fw = tmp_path / "firmware.hex"
    fw.write_text(":00000001FF", encoding="utf-8")
    cmd = Stm32FlashProvider(board_cfg)._openocd_command("verify", str(fw))
    joined = " ".join(cmd)
    assert "verify_image" in joined
    assert "program" not in joined


def test_transport_selected_before_target_cfg(board_cfg: dict,
                                              tmp_path: Path) -> None:
    """`transport select` 必须排在 `-f target/*.cfg` 之前。

    排在后面时 target cfg 会先 auto-select 并打 DEPRECATED 警告 —— 不致命，
    但会让「谁选的 swd」变得含糊。
    """
    fw = tmp_path / "firmware.hex"
    fw.write_text(":00000001FF", encoding="utf-8")
    cmd = Stm32FlashProvider(board_cfg)._openocd_command("flash", str(fw))
    i_transport = cmd.index("transport select swd")
    i_target = next(i for i, a in enumerate(cmd)
                    if a == "-f" and str(cmd[i + 1]).endswith("stm32h7x.cfg"))
    assert i_transport < i_target


def test_detect_port_does_not_fall_back_to_arbitrary_port(board_cfg: dict,
                                                          monkeypatch) -> None:
    """没有串口匹配 port_hint 时必须返回 None，**不能**退而取第一个串口。

    退而取之的后果：在有主板 COM1 的机器上会去读 COM1，读到空数据；
    而 S5 永不阻断，于是"回读失败"被静默吸收成"验证通过"。
    """
    import serial.tools.list_ports as lp

    class _Port:
        def __init__(self, device, description):
            self.device = device
            self.description = description
            self.manufacturer = None

    monkeypatch.setattr(lp, "comports",
                        lambda: [_Port("COM1", "Communications Port")])
    assert Stm32FlashProvider(board_cfg).detect_port() is None


def test_detect_port_accepts_the_declared_bridge(board_cfg: dict,
                                                  monkeypatch) -> None:
    import serial.tools.list_ports as lp

    class _Port:
        def __init__(self, device, description):
            self.device = device
            self.description = description
            self.manufacturer = None

    monkeypatch.setattr(lp, "comports", lambda: [
        _Port("COM1", "Communications Port"),
        _Port("COM7", "USB-SERIAL CH340"),
    ])
    assert Stm32FlashProvider(board_cfg).detect_port() == "COM7"


def test_flash_missing_firmware_is_reported(board_cfg: dict) -> None:
    result = Stm32FlashProvider(board_cfg).flash("/no/such/firmware.hex")
    assert not result.success
    assert "not found" in result.stderr.lower()


def test_bytes_written_falls_back_to_file_size(tmp_path: Path) -> None:
    bin_file = tmp_path / "firmware.bin"
    bin_file.write_bytes(b"\x00" * 1024)
    assert Stm32FlashProvider._bytes_written("", str(bin_file)) == 1024


def test_bytes_written_prefers_openocd_report() -> None:
    out = "Info : 4096 bytes written at address 0x08000000"
    assert Stm32FlashProvider._bytes_written(out, "x.hex") == 4096


# --------------------------------------------------------------------------
# 6. 共享诊断解析（avr / arm 同源）
# --------------------------------------------------------------------------


def test_gcc_diagnostics_parses_error_and_warning() -> None:
    stderr = (
        "src/main.c:12:5: error: 'HAL_Init' undeclared here\n"
        "src/main.c:20:1: warning: unused variable 'x'\n"
    )
    diags = parse_gcc_diagnostics(stderr)
    assert [(d.severity, d.line, d.column) for d in diags] == [
        ("error", 12, 5), ("warning", 20, 1)]


def test_gcc_diagnostics_catches_fatal_error() -> None:
    """`fatal error:` 以前的正则漏掉过（`fatal ` 卡在 `\\s*` 前面）。"""
    diags = parse_gcc_diagnostics("x.c:1:10: fatal error: stm32h7xx.h: No such file")
    assert len(diags) == 1
    assert diags[0].severity == "error"
    assert "No such file" in diags[0].message


def test_gcc_diagnostics_skips_notes() -> None:
    diags = parse_gcc_diagnostics("x.c:3:1: note: expected 'int *' but got 'char *'")
    assert diags == []


def test_gcc_diagnostics_captures_undefined_reference() -> None:
    stderr = ("/usr/bin/ld: main.o: in function `main':\n"
              "main.c:5: undefined reference to `HAL_GPIO_TogglePin'\n"
              "collect2: error: ld returned 1 exit status\n")
    diags = parse_gcc_diagnostics(stderr)
    assert any("undefined reference" in d.message for d in diags)
    assert any("ld returned" in d.message for d in diags)


def test_arduino_route_shares_the_same_parser() -> None:
    """两条编译路线共用一份解析 —— 避免第二次修 bug 时分叉。"""
    from firmforge.providers.arduino.build import ArduinoBuildProvider
    stderr = "sketch.ino:7:3: error: expected ';' before '}' token"
    assert ([d.message for d in ArduinoBuildProvider.parse_build_errors(None, stderr)]
            == [d.message for d in parse_gcc_diagnostics(stderr)])
