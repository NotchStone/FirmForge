"""MCP 工具面必须与 CLI 命令面一一对应。

为什么需要这个文件：2026-10-28 实测发现 CLI 有 10 条命令，MCP 只有 6 个工具
（缺 review / verify / status / inspect），已有的 `ff_build` 还漏了参数。
根因不是「忘了改」，而是**没有任何东西会报警**：

  · 手写的 `TOOL_SCHEMAS` 定义了 6 个工具的 schema，但全仓无人引用（142 行死代码，
    其中 `ff_context` 的 topic 值域还是错的）；
  · `tests/` 下一条 MCP 测试都没有。

所以这里的断言都是「结构性」的：新增命令而没暴露工具 → 红；工具用了 CLI 里
不存在的参数 → 红；又多出一份手写 schema → 红。豁免必须写在表里并给理由。
"""

from __future__ import annotations

import argparse
import importlib
import inspect

import pytest

from firmforge.adapters import cli, mcp_server

#: 有意**不**暴露给 MCP 的 CLI 命令。每条必须写理由 ——
#: 没有理由的豁免，等于把「漏掉」合法化。
NOT_EXPOSED: dict[str, str] = {
    "setup": (
        "装工具链是人在装机时做的一次性动作，不是 Agent 的职责；"
        "且它只代装 AVR 那一套（STM32 的 arm-none-eabi/OpenOCD 要手动装），"
        "让 Agent 调用会得到「装完了但 STM32 还是不能编译」的错觉"
    ),
}

#: MCP 独有、没有对应 CLI 命令的工具。同样要写理由。
MCP_ONLY: dict[str, str] = {
    "ff_monitor": (
        "面板是 MCP 侧唯一的人机界面入口：ff_run 默认不开面板（2026-10-28 定），"
        "人在 IDE 里想实时看串口时走这里。CLI 用户可以直接打开 .ff-run/serial_live.html"
    ),
}


def _cli_commands() -> dict[str, argparse.ArgumentParser]:
    """{子命令名: 它的 parser}。用 argparse 自己的结构，不解析 --help 文本。"""
    parser = cli.setup_argument_parser()
    for action in parser._actions:                   # noqa: SLF001 — argparse 无公开 API
        if isinstance(action, argparse._SubParsersAction):  # noqa: SLF001
            return dict(action.choices)
    return {}


def _cli_dests(sub: argparse.ArgumentParser) -> set[str]:
    """该子命令接受的所有 dest（含 --json / -v 这类通用项）。"""
    return {a.dest for a in sub._actions}            # noqa: SLF001


def _global_dests() -> set[str]:
    parser = cli.setup_argument_parser()
    return {a.dest for a in parser._actions}          # noqa: SLF001


def _tool_funcs() -> dict[str, object]:
    return {f.__name__: f for f in mcp_server.MCP_TOOL_FUNCS}


def test_every_cli_command_is_exposed_or_explicitly_exempt():
    """新增 CLI 命令必须同时更新 MCP，否则这里红。"""
    exposed = set(_tool_funcs())
    missing = []
    for name in _cli_commands():
        tool = f"ff_{name}"
        if tool in exposed or name in NOT_EXPOSED:
            continue
        missing.append(f"ff {name} → 缺 MCP 工具 {tool}")
    assert not missing, (
        "以下 CLI 命令没有 MCP 工具，也没有登记豁免：\n  " + "\n  ".join(missing)
        + "\n（要暴露就加进 MCP_TOOL_FUNCS；确实不该暴露就写进 NOT_EXPOSED 并给理由）"
    )


def test_no_mcp_tool_without_a_cli_command():
    """反向：MCP 工具必须在 CLI 里有对应命令，或者在 MCP_ONLY 里写明理由。"""
    commands = set(_cli_commands())
    orphan = [t for t in _tool_funcs()
              if t.removeprefix("ff_") not in commands and t not in MCP_ONLY]
    assert not orphan, (
        "以下 MCP 工具没有对应的 CLI 命令：\n  " + "\n  ".join(orphan)
        + "\n（要么补 CLI 命令，要么写进 MCP_ONLY 并给理由）"
    )


def test_mcp_tool_names_are_unique_and_match_cli_naming():
    names = [f.__name__ for f in mcp_server.MCP_TOOL_FUNCS]
    assert len(names) == len(set(names)), f"工具名重复：{names}"
    for name in names:
        assert name.startswith("ff_"), (
            f"{name} 不符合「ff_<子命令>」命名 —— 工具名与命令名对不上时，"
            f"调用方只能靠猜哪个工具对应哪条命令")


@pytest.mark.parametrize("tool_name", [f.__name__ for f in mcp_server.MCP_TOOL_FUNCS])
def test_mcp_params_exist_in_the_matching_cli_command(tool_name: str):
    """MCP 工具的每个参数都必须是 CLI 那条命令也接受的。

    否则会出现「MCP 能传、CLI 不认」（或反过来）：两套接口开始各自演化，
    参数名的含义也会跟着漂 —— `--app` 两义就是这么长出来的。
    """
    if tool_name in MCP_ONLY:
        pytest.skip(MCP_ONLY[tool_name])

    sub = _cli_commands()[tool_name.removeprefix("ff_")]
    allowed = _cli_dests(sub) | _global_dests() | {"workspace", "boards_dir"}
    params = set(inspect.signature(_tool_funcs()[tool_name]).parameters)
    unknown = params - allowed
    assert not unknown, (
        f"{tool_name} 的参数 {sorted(unknown)} 在 `ff {tool_name.removeprefix('ff_')}` "
        f"里不存在。CLI 该命令接受的参数：{sorted(_cli_dests(sub))}"
    )


def test_tool_functions_are_importable_without_the_mcp_sdk():
    """工具函数定义在模块级、不带装饰器 —— 没有 mcp 库的环境也要能反射。

    这条守的是「schema 只有一份」：如果工具定义被塞回
    `if MCP_AVAILABLE:` 里面，CI 里没装 mcp 时就反射不到签名，
    覆盖关系又变成只能靠人肉比对。
    """
    mod = importlib.import_module("firmforge.adapters.mcp_server")
    for fn in mod.MCP_TOOL_FUNCS:
        assert callable(fn)
        assert inspect.signature(fn).parameters is not None


def test_no_handwritten_tool_schema_left():
    """手写 schema 是第二份「说明」，一定会和签名漂。

    旧 TOOL_SCHEMAS 的 ff_context 把 topic 值域写成 gpio/uart/spi/i2c/adc/timer/pwm，
    实际实现只认 registers/pins/baud/all —— 而且它全仓无人引用，没人会去校验。
    """
    assert not hasattr(mcp_server, "TOOL_SCHEMAS"), (
        "又出现了手写的 TOOL_SCHEMAS。schema 只能由函数签名生成一份；"
        "手写的那份不会被任何代码读取，只会静默过期")


def test_hex_addr_parsing_matches_cli():
    """MCP 的 pc 收十六进制字符串，规则必须与 CLI 的 --pc 一致。"""
    assert mcp_server._hex_addr("0x08001D78") == 0x08001D78
    assert mcp_server._hex_addr("08001D78") == 0x08001D78
    assert mcp_server._hex_addr("0x0800_1D78") == 0x08001D78
    assert mcp_server._hex_addr("0x08001D78") == cli._parse_pc("0x08001D78")


def test_flash_takes_build_not_app():
    """`ff flash` 的「构建缓存应用名」必须叫 build，且不再接受 app。

    app 在 run/build/review 里是源码目录 —— 同名两义会让 `--app ./src` 去找
    一个叫 `./src` 的缓存目录，报「没有产物」，看起来像缓存的问题。
    """
    sub = _cli_commands()["flash"]
    opts = {s for a in sub._actions for s in a.option_strings}
    assert "--build" in opts
    assert "--app" in opts, "旧写法要留一条带迁移提示的入口，不能直接消失"
    assert "build" in _cli_dests(sub)


def test_serial_evidence_falls_back_to_sample_lines():
    """`ff_run` 与 `ff_verify` 必须给同一份串口证据。

    2026-10-28 实测：`ff_run` 的 `serial_lines` 恒为空，因为它读的
    `serial_output` 字段 S5 早已不写；同一次调用里 `verdict` 却是 `verified`。
    Agent 看到「验证通过 + 零行输出」，只能二选一相信 —— 这就是自相矛盾的数据。
    """
    from types import SimpleNamespace

    from firmforge.adapters.commands import serial_evidence

    only_samples = SimpleNamespace(details={"sample_lines": ["HB ver=1 tick=1",
                                                             "HB ver=1 tick=2"]})
    assert serial_evidence(only_samples) == ["HB ver=1 tick=1", "HB ver=1 tick=2"]

    with_full = SimpleNamespace(details={"sample_lines": ["a"],
                                         "serial_output": "a\nb\nc"})
    assert serial_evidence(with_full) == ["a", "b", "c"], "有全文时用全文"

    assert serial_evidence(None) == []
    assert serial_evidence(SimpleNamespace(details={})) == []
