"""OpenOCD 事务层 —— 一次 `init` → 若干命令 → `shutdown`。

为什么单独一层（而不是塞进 flash.py）
-------------------------------------
烧录与观测用的是**同一套连接参数**（`interface_cfg` / `target_cfg` /
`transport` / `speed_khz`，全部来自 `board.yaml`），但**生命周期不同**：

* 烧录 = 一次性事务，`program ... exit` 跑完就退；
* 观测 = 「先跑几毫秒 → 暂停 → 连着读好几轮 → 恢复运行」，且必须保证
  退出时现场被复原（看门狗冻结位、CPU 运行状态）。

两者的 cfg 拼接如果各写一份，迟早会漂移 —— 而 `transport select` 的顺序
**必须**排在 `-f target/*.cfg` 之前（target cfg 会自己 auto-select transport
并因此打 DEPRECATED 警告，先选则警告消失且行为一致）。所以这里只做一件事：
把「怎么拼一条 openocd 命令行」和「怎么把一个 Tcl 脚本跑成结构化结果」定死。

退出码不可信（与 flash.py 同一条铁律）
--------------------------------------
OpenOCD 有多条路径会打印错误但返回 0。更麻烦的是**脚本中途失败**：`-f xxx.tcl`
里第 3 行报错，openocd 仍可能带着 0 退出，而你已经拿到半份数据。所以每个
脚本末尾必须打 `FF_DONE=1`，没有这一行 = 会话不完整，结果整体作废。
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from firmforge.providers.stm32.toolchain import Stm32Toolchain, resolve_toolchain
from firmforge.providers.textio import run_text

logger = logging.getLogger(__name__)

#: 脚本跑到底的标记。缺这一行 = 会话不完整，数据不可信。
DONE_MARKER = "FF_DONE=1"


def base_args(toolchain: Stm32Toolchain, flash_cfg: dict[str, Any]) -> list[str]:
    """拼 openocd 的连接参数（不含动作）。

    顺序有讲究：`transport select` / `adapter speed` 必须排在
    `-f target/*.cfg` 之前。见模块文档字符串。
    """
    cmd = [
        toolchain.openocd,
        "-s", str(toolchain.openocd_scripts),
        "-f", str(flash_cfg.get("interface_cfg", "interface/cmsis-dap.cfg")),
    ]
    transport = flash_cfg.get("transport")
    if transport:
        cmd += ["-c", f"transport select {transport}"]
    speed = flash_cfg.get("speed_khz")
    if speed:
        cmd += ["-c", f"adapter speed {speed}"]
    cmd += ["-f", str(flash_cfg.get("target_cfg", "target/stm32h7x.cfg"))]
    return cmd


def _first_error_line(output: str) -> str:
    """取第一条有信息量的错误行（`Error: ` 后面为空的不算）。"""
    for raw in output.splitlines():
        line = raw.strip()
        if line.startswith("Error:"):
            body = line[len("Error:"):].strip()
            if body:
                return body
    for raw in output.splitlines():
        line = raw.strip()
        if "in procedure" in line or "unable to" in line.lower():
            return line
    return ""


@dataclass
class OcdRun:
    """一次 OpenOCD 事务的结果。"""

    ok: bool
    stdout: str = ""
    stderr: str = ""
    elapsed_ms: float = 0.0
    command: list[str] = field(default_factory=list)
    error: str = ""

    @property
    def text(self) -> str:
        return (self.stdout or "") + "\n" + (self.stderr or "")


def run_script(script: str, *,
               board_config: dict[str, Any],
               toolchain: Stm32Toolchain | None = None,
               timeout: float = 90.0) -> OcdRun:
    """把 `script` 写成临时 .tcl 交给 openocd 执行，返回结构化结果。

    `script` 里用 `echo FF_xxx=yyy` 打标记行，由调用方解析 —— 比让 Python
    去正则匹配 openocd 的各种打印格式稳得多（`reg` 在 0.12 前后格式变过）。
    """
    tc = toolchain or resolve_toolchain()
    problems = [p for p in tc.problems() if "openocd" in p or "scripts" in p]
    if problems:
        return OcdRun(ok=False, error="STM32 调试链路不完整：\n  - " + "\n  - ".join(problems))

    flash_cfg = (board_config.get("flash") or {})
    cmd = base_args(tc, flash_cfg)

    tmpdir = Path(tempfile.mkdtemp(prefix="ff-ocd-"))
    script_path = tmpdir / "session.tcl"
    try:
        # 换行统一成 \n；openocd 的 Tcl 解析器不认 CRLF 里的 \r 作续行。
        script_path.write_text(script.replace("\r\n", "\n"), encoding="utf-8")
        cmd += ["-f", str(script_path)]
        logger.info("OpenOCD 事务: %s", " ".join(cmd))

        start = time.perf_counter()
        try:
            r = run_text(cmd, timeout=timeout)
        except subprocess.TimeoutExpired:
            return OcdRun(
                ok=False, command=cmd,
                elapsed_ms=(time.perf_counter() - start) * 1000,
                error=f"OpenOCD 超时（{timeout:.0f} s）—— 探针未连接或目标未上电？",
            )
        except OSError as exc:
            return OcdRun(
                ok=False, command=cmd,
                elapsed_ms=(time.perf_counter() - start) * 1000,
                error=f"无法启动 OpenOCD: {exc}",
            )

        elapsed = (time.perf_counter() - start) * 1000
        out = (r.stdout or "") + (r.stderr or "")

        if DONE_MARKER not in out:
            # 半份数据比没有更危险：一律判失败。
            # 把**具体那一行**带出来 —— 只说"缺 FF_DONE"等于什么都没说；
            # 常见的真实原因是 halt 期间目标被看门狗复位，OpenOCD 会打
            # "Error: ..." 或 "in procedure ... " 然后会话就断在那儿。
            detail = _first_error_line(out)
            return OcdRun(
                ok=False, stdout=r.stdout or "", stderr=r.stderr or "",
                elapsed_ms=elapsed, command=cmd,
                error="OpenOCD 会话未跑完（缺 FF_DONE 标记）"
                      + (f"：{detail}" if detail else
                         " —— 目标可能在会话中途复位/断开了"),
            )

        # FF_DONE 之后的 Error 才算致命；之前的一律记进 stderr 由调用方决定。
        if r.returncode != 0:
            return OcdRun(
                ok=False, stdout=r.stdout or "", stderr=r.stderr or "",
                elapsed_ms=elapsed, command=cmd,
                error=f"OpenOCD 返回码 {r.returncode}",
            )

        return OcdRun(ok=True, stdout=r.stdout or "", stderr=r.stderr or "",
                      elapsed_ms=elapsed, command=cmd)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


__all__ = ["base_args", "run_script", "OcdRun", "DONE_MARKER"]
