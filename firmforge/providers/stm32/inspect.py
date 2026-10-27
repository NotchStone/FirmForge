"""STM32 只读观测（`ff inspect`）—— CPU 停在哪、关键变量是什么、上次为什么复位。

定位（与 S5 的分工不能混）
--------------------------
* S5（串口回读）只回答：「有没有字节」和「你给的断言命中没有」；
* inspect 只回答：「CPU 在哪、寄存器是什么」。

两者都**不做业务判断** —— 这次自检算不算通过，由调用方（Agent / 人）看数据自己定。

只读
----
默认不写目标。三处例外，全部显式、可逆，且都写进输出：

1. `halt` / `resume` —— 暂停与恢复。默认 `resume`，把 CPU 放回去；
2. **看门狗冻结位**。内核停住但 IWDG 仍按 LSI 计数，暂停超过一个看门狗周期
   芯片就复位 —— 实测这块板子的固件把周期配成约 10 ms（RLR=10、PR=/32、
   LSI 32 kHz），而一次会话约 0.9 s，不冻结根本读不完一条完整数据。
   **但冻结这件事 OpenOCD 自己已经做了**：`target/stm32h7x.cfg` 的
   `examine-end` 钩子无条件写 `DBGMCU_APB4FZ1 |= 0x000C0000`（bit18 IWDG1
   + bit19，实测进入会话时读到的原值就是 `0xC0000`）。所以这里的主要价值是
   「**回读校验**」而不是「替它写」：位没置上必须说出来，不能假设配置生效。
   `--no-freeze-watchdog` 是**主动清位**（对照实验用）—— 只"不写"的话，
   这个开关会被 OpenOCD 的默认行为掩盖，等于没作用。
3. `--clear-reset-flags`（默认关）—— 写 RCC_RSR 的 RMVF 位清复位标志。

看门狗冻结位是**内置常量，不是从知识库查的**
------------------------------------------------
`firmforge` 的 STM32 寄存器知识库来自 SVD，128 个外设组里**没有 DBGMCU**
（实测：`'DBGMCU' in register_groups` 为 False）。所以这里不能用「查不到就跳过」，
否则冻结会静默失效 —— 那是本模块最危险的一种失败。

常量取自厂商 CMSIS 头 `stm32h743xx.h`：

    #define DBGMCU_BASE   (0x5C001000UL)
    DBGMCU_TypeDef: IDCODE@0x00 CR@0x04 ... APB4FZ1@0x54
    #define DBGMCU_APB4FZ1_DBG_IWDG1_Pos  (18U)

即 **0x5C001054, bit18**。注意寄存器在头文件里叫 `APB4FZ1`（不是 `APB4FZR1`），
按 `FZR` 去搜是搜不到的。

复位标志的判读有一张必须照抄的优先级表
--------------------------------------
RM0433 Rev 8 §8.4.4 Table 56 的关键点不是"有哪些位"，而是**同一次复位会置多个位**：

* IWDG1 超时 → `IWDG1RSTF=1` **且** `PINRSTF=1`；
* 上电 → `PORRSTF=1` 且 `PINRSTF=1` 且 `BORRSTF=1`。

所以先看 `PINRSTF` 会把「看门狗复位」误判成「按了复位键」。判定顺序必须从
最根因往最笼统走，见 `_RESET_PRIORITY`。

还有一个更隐蔽的坑：**RCC_RSR 的上电复位值是 0x00FE0000**（同手册 Table 65），
也就是 CPURSTF/D1/D2/BOR/PIN/POR 六位天生就是 1。固件若从不清标志，你每次
读到的都是这个值，结论永远是「上电复位」。检测到该值时必须直说「结论不可信」，
而不是照表解出一个 primary。
"""

from __future__ import annotations

import datetime
import fnmatch
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from firmforge.providers.stm32.debug import OcdRun, run_script
from firmforge.providers.stm32.toolchain import Stm32Toolchain, resolve_toolchain
from firmforge.providers.textio import run_text

logger = logging.getLogger(__name__)

SCHEMA = "ff.inspect/1"

# -- 目标相关常量（依据见模块文档字符串） --------------------------------

#: DBGMCU 调试冻结寄存器（APB4），位于 DBGMCU_BASE(0x5C001000) + 0x54
DBGMCU_APB4FZ1 = 0x5C001054
#: bit18 = DBG_IWDG1：置 1 后内核暂停期间 IWDG1 停止计数
IWDG1_FREEZE_BIT = 1 << 18

#: RCC_RSR（0x58024400 + 0x0D0）
RCC_RSR = 0x580244D0
#: RSR 的 RMVF 位：写 1 清全部复位标志
RSR_RMVF_BIT = 1 << 16
#: RSR 上电复位值（RM0433 Table 65）。读到它 = 固件从未清过标志。
RSR_POWER_ON_VALUE = 0x00FE0000

#: 复位标志判定顺序：**从最根因到最笼统**。
#: 依据 RM0433 Table 56 —— 同一次复位会同时置多位（IWDG1 会连带 PIN，
#: 上电会连带 PIN+BOR），所以具体源必须排在笼统源前面。
_RESET_PRIORITY: tuple[tuple[str, str, str], ...] = (
    ("LPWRRSTF", "LPWR", "非法 DStandby / CStop 复位（软件把内核停了）"),
    ("IWDG1RSTF", "IWDG1", "独立看门狗超时 —— 固件没喂狗或已卡死"),
    ("WWDG1RSTF", "WWDG1", "窗口看门狗超时"),
    ("SFTRSTF", "SFT", "软件复位（NVIC_SystemReset / 调试器）"),
    ("PORRSTF", "POR", "上电复位"),
    ("BORRSTF", "BOR", "掉电复位（供电跌破阈值）"),
    ("PINRSTF", "PIN", "外部复位引脚 / 调试器复位"),
    ("CPURSTF", "CPU", "仅内核域复位"),
    ("D1RSTF", "D1", "D1 域复位"),
    ("D2RSTF", "D2", "D2 域复位"),
)

#: 单次输出上限 —— 要的是判据，不是 dump。
MAX_WORDS_PER_SYMBOL = 32
MAX_REGS_PER_PERIPHERAL = 24

_MARKER_RE = re.compile(r"^FF_([A-Za-z0-9_]+)=(.*)$")
_MEM_MARK_RE = re.compile(r"^MEM_0x([0-9a-fA-F]+)$")


# --------------------------------------------------------------------------
# 请求
# --------------------------------------------------------------------------

class InspectError(RuntimeError):
    """观测前提不成立 —— 必须在**碰硬件之前**停下。

    单独一个异常类型的原因：这类错误发生在会话建立前，绝不能走到
    halt / 冻结看门狗那一步（那会改动目标状态，为一次注定要重跑的
    命令复位板子是不划算的）。候选清单一起带出去，调用方照着改就行。
    """

    def __init__(self, message: str, *, candidates: list[str] | None = None,
                 hint: str = "") -> None:
        super().__init__(message)
        self.candidates = list(candidates or [])
        self.hint = hint


@dataclass
class InspectRequest:
    """一次观测请求。默认值即"人最常用"的那条路径。"""

    elf: str | None = None
    #: 应用名（构建缓存里的子目录名）。与 `elf` 二选一，比 `elf` 更稳 ——
    #: 它不依赖调用者知道 B 区绝对路径。
    app: str | None = None
    #: 只解析一个 PC 的源码位置，**不连探针**。故障现场从串口拿到 pc 后
    #: 最常用的一次性查询；`None` = 走在线模式读当前 halt 的 PC。
    pc: int | None = None
    symbols: list[str] = field(default_factory=list)
    sym_globs: list[str] = field(default_factory=list)
    peripherals: list[str] = field(default_factory=list)
    where: bool = True
    resume: bool = True
    freeze_watchdog: bool = True
    clear_reset_flags: bool = False
    symbol_notes: str | None = None
    timeout: float = 90.0


# --------------------------------------------------------------------------
# 主入口
# --------------------------------------------------------------------------

def inspect(board_config: dict[str, Any], req: InspectRequest, *,
            toolchain: Stm32Toolchain | None = None) -> dict[str, Any]:
    """执行一次观测，返回 `ff.inspect/1` payload（含 warnings，永不编默认值）。"""
    start = time.perf_counter()
    tc = toolchain or resolve_toolchain()
    warnings: list[str] = []
    # 知识库推迟到确认要走在线路径之后再加载：`--pc` 离线解析只需要
    # addr2line，加载 2000+ 寄存器的知识库纯粹是白等。

    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "target": _target_block(board_config, tc),
        "mode": "online",
        "reset_cause": None,
        "location": None,
        "stack": {"sp": None, "lr": None, "fault": None},
        "symbols": [],
        "peripherals": [],
        "serial": None,          # 本版本不抓串口（与 halt 严格互斥，见 warnings）
        "warnings": warnings,
        "elapsed_ms": 0,
    }
    payload["serial_note"] = ("inspect 不抓串口：CPU 暂停后串口不再产生新字节，"
                              "同时抓会得到「较早时刻的 PC + 较晚时刻的串口」这类错位数据。"
                              "串口请用 ff run --expected 或 ff monitor。")

    # --- 1. 找出要读的东西 ---------------------------------------------
    try:
        elf_path, elf_note = _resolve_elf(board_config, req, warnings)
    except InspectError as exc:
        # 前提不成立就**不连探针**：会话会 halt 目标、冻结看门狗，
        # 为一条注定要重跑的命令改动目标状态不划算。
        payload["error"] = str(exc)
        payload["candidates"] = exc.candidates
        if exc.hint:
            payload["hint"] = exc.hint
        payload["elapsed_ms"] = round((time.perf_counter() - start) * 1000)
        return payload

    # ELF 一旦定下来就先回显：后面任何一行输出都必须能追溯是哪个固件，
    # 包括「--pc 离线解析」这种根本不连板子的路径。
    payload["target"]["elf"] = elf_path
    if elf_path:
        try:
            st = Path(elf_path).stat()
            payload["target"]["elf_mtime"] = datetime.datetime.fromtimestamp(
                st.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            payload["target"]["elf_size"] = st.st_size
        except OSError:
            pass

    # --- 1b. 离线 PC 解析（--pc）----------------------------------------
    # 故障现场从串口拿到 pc 后只需要 addr2line，完全不必连板子 ——
    # 这个分支必须在构建读规划、跑 OpenOCD 之前返回。
    if req.pc is not None:
        payload["mode"] = "offline"
        payload["target"]["state"] = "not-contacted"
        payload["target"]["halted"] = None      # 三态：None = 压根没连
        payload["target"]["elf"] = elf_path
        if not elf_path:
            payload["warnings"].append(elf_note or "未找到 ELF：--pc 无法解析源码行")
        else:
            payload["location"] = _location(elf_path, req.pc, tc, warnings)
        payload["elapsed_ms"] = round((time.perf_counter() - start) * 1000)
        return payload

    syms = _collect_symbols(elf_path, tc, req, warnings) if elf_path else []

    reads: list[tuple[int, int, int]] = []      # (addr, count, width_bytes)
    sym_plan: list[dict[str, Any]] = []
    for s in syms:
        if s["addr"] is None:
            continue
        words = max(1, min(MAX_WORDS_PER_SYMBOL, (s["size"] + 3) // 4 or 1))
        if s["size"] > 4:
            warnings.append(
                f"符号 {s['name']} 大小 {s['size']} B，只读前 {words} 个字"
                f"（上限 {MAX_WORDS_PER_SYMBOL} 字）")
        reads.append((s["addr"], words, 4))
        sym_plan.append({**s, "words_wanted": words})

    kb = _load_kb(board_config, warnings)
    periph_plan = _peripheral_plan(kb, req.peripherals, warnings)
    for _p in periph_plan:
        for r in _p["registers"]:
            reads.append((r["address"], 1, max(1, r["size"] // 8)))

    # 复位原因：RSR 必须显式进读列表 —— 它不属于任何"外设组"（RCC 有几百个
    # 寄存器，不可能整组读），漏掉它就是每次都报"复位原因未知"。
    reads.append((RCC_RSR, 1, 4))

    # 去重：同一地址只读一次
    seen: dict[int, tuple[int, int]] = {}
    for addr, count, width in reads:
        prev = seen.get(addr)
        if prev is None or count > prev[0]:
            seen[addr] = (count, width)
    unique_reads = [(a, c, w) for a, (c, w) in sorted(seen.items())]

    # --- 2. 跑一次会话 --------------------------------------------------
    script = _build_script(req, unique_reads, warning_sink=warnings)
    run: OcdRun = run_script(script, board_config=board_config,
                             toolchain=tc, timeout=req.timeout)
    payload["elapsed_ms"] = round((time.perf_counter() - start) * 1000)

    if not run.ok:
        payload["warnings"].append(run.error or "OpenOCD 会话失败")
        payload["target"]["state"] = "unknown"
        _m = re.search(r"CMSIS-DAP:\s*Serial#\s*=\s*(\S+)", run.text)
        if _m:
            payload["target"]["probe"] = _m.group(1)
        if not req.freeze_watchdog:
            payload["warnings"].append(
                "本次按 --no-freeze-watchdog 主动清除了看门狗冻结位：暂停期间 "
                "IWDG 照常计数，目标一复位会话就断在这儿。要完整快照请去掉该开关。")
        payload["elapsed_ms"] = round((time.perf_counter() - start) * 1000)
        return payload

    markers = _parse_markers(run.text)
    mem = _parse_mem(markers)

    if markers.get("INIT") != "OK":
        payload["warnings"].append("OpenOCD init 失败，目标未连接")
        payload["target"]["state"] = "unknown"
        return payload
    if markers.get("HALT") != "OK":
        payload["warnings"].append(
            f"halt 失败（{markers.get('HALT', '未返回')}），以下数据不可信")

    payload["target"].update(_target_state(markers, run))
    payload["target"]["state"] = ("halted" if markers.get("HALT") == "OK" else "unknown")
    # ELF 已在会话之前回显（见 1b 之前的代码），这里不再重复设置 ——
    # 但会话失败的分支（`if not run.ok`）仍要自己补一次，它比回显更早返回。
    payload["reset_cause"] = _reset_cause(mem.get(RCC_RSR), warnings)

    # --- 3. 位置与符号 --------------------------------------------------
    regs = {k[4:]: v for k, v in markers.items() if k.startswith("REG_")}
    pc = _as_int(regs.get("pc"))
    if req.where and pc is not None:
        payload["location"] = _location(elf_path, pc, tc, warnings)
    payload["stack"]["sp"] = _hex(regs.get("sp"))
    payload["stack"]["lr"] = _hex(regs.get("lr"))
    payload["stack"]["fault"] = _fault_state(regs, warnings)
    _sanity_check_snapshot(payload, warnings)

    payload["symbols"] = _symbol_values(sym_plan, mem, req)
    payload["peripherals"] = _peripheral_values(periph_plan, mem)

    # 停在复位向量 = 快照是「复位初值」，不是「运行状态」。
    # 不说这一句，用户会把全 0 的变量当成「固件卡在第一步」。
    if payload["location"] and payload["location"].get("function") == "Reset_Handler":
        payload["warnings"].append(
            "PC 停在 Reset_Handler（复位向量）：这次快照是复位初值，不反映固件运行状态。"
            "要么固件刚被复位，要么根本没有启动。")
    if markers.get("RESUMED") == "0" and req.resume:
        payload["warnings"].append("resume 未执行成功 —— 目标当前仍处于暂停状态")
    if req.resume and markers.get("RESUMED") == "1":
        payload["target"]["resumed"] = True
    elif not req.resume:
        payload["target"]["resumed"] = False

    if not elf_path:
        payload["warnings"].append(elf_note or "未找到 ELF：符号与源码行不可用")
    payload["elapsed_ms"] = round((time.perf_counter() - start) * 1000)
    return payload


# --------------------------------------------------------------------------
# 目标 / 连接信息
# --------------------------------------------------------------------------

def _target_block(board_config: dict[str, Any], tc: Stm32Toolchain) -> dict[str, Any]:
    flash = board_config.get("flash") or {}
    return {
        "board_id": board_config.get("board_id"),
        "mcu": (board_config.get("mcu") or {}).get("chip"),
        "state": "unknown",
        "halt_reason": None,
        "watchdog_frozen": None,
        "probe": None,
        "speed_khz": flash.get("speed_khz"),
        "openocd": tc.openocd or None,
    }


def _target_state(markers: dict[str, str], run: OcdRun) -> dict[str, Any]:
    m = re.search(r"CMSIS-DAP:\s*Serial#\s*=\s*(\S+)", run.text)
    prior = markers.get("PRIOR_STATE")
    # watchdog_frozen **必须是回读值**，不能是"我设了所以是 true"。
    # 假冻结比不冻结更危险：它会让你相信一份其实正在被看门狗打断的快照。
    fz_state = markers.get("FZ_STATE")
    frozen: bool | None = None
    if fz_state in ("0", "1"):
        frozen = fz_state == "1"
    return {
        "probe": m.group(1) if m else None,
        # 进会话前它在跑还是在停 —— "本来就停着"和"被我停了"必须能分开
        "state_prior": prior if prior and prior != "unknown" else None,
        "halted": markers.get("HALT") == "OK",
        "halt_reason": "debug-request",
        "watchdog_frozen": frozen,
        # 本次是否由 inspect 置位。回读为 True 但 applied=False，说明
        # 位是**之前就有的**（DBGMCU 只在 POR 时复位，系统复位不清），
        # 这时候说"我冻结了"是抢别人的功劳，也会误导 --no-freeze 的效果。
        "watchdog_freeze_applied": markers.get("FZ_APPLIED") == "1",
        "watchdog_freeze_prior": markers.get("FZ_PRIOR"),
    }


def _sanity_check_snapshot(payload: dict[str, Any], warnings: list[str]) -> None:
    """拦「读到了但全是坏值」——这是最危险的一种成功。

    实测（`--no-freeze-watchdog`）：目标在读取过程中被看门狗复位，命令仍然
    走完、退出码 0，但 PC 与 SP 都是 `0x08004FBC`（同一个 flash 地址），
    xPSR 解出 IRQ428。这种快照比报错更能骗人，必须显式标注不可信。
    """
    t = payload.get("target") or {}
    if t.get("watchdog_frozen") is False:
        warnings.append(
            "看门狗未冻结：本次快照可能在中途被复位打断。"
            "下面的寄存器/变量值不一定属于同一时刻，结论请打折看待。")

    sp = payload["stack"].get("sp")
    pc = (payload.get("location") or {}).get("pc")
    if sp and pc and sp == pc:
        warnings.append(
            f"SP 与 PC 相同（{sp}）：寄存器快照不一致，几乎可以确定目标在读取期间复位过。"
            "本次数据不可信。")
    if sp:
        try:
            spv = int(sp, 16)
        except ValueError:
            return
        if not _is_plausible_stack(spv):
            warnings.append(
                f"SP={sp} 不落在任何 RAM 区间（DTCM/AXI-SRAM/SRAM1-4），"
                "栈指针非法 —— 本次快照不可信。")


#: Cortex-M7 上 SP 可能落在的 RAM 区间（只用于合理性判断，不是完整内存映射）
_RAM_RANGES = (
    (0x00000000, 0x00020000),   # ITCM（部分工程把栈放这里）
    (0x20000000, 0x20040000),   # DTCM
    (0x20200000, 0x20240000),   # AXI SRAM（部分型号）
    (0x24000000, 0x24100000),   # AXI SRAM
    (0x30000000, 0x30050000),   # AHB SRAM1/2/3
    (0x38000000, 0x38010000),   # SRAM4
)


def _is_plausible_stack(sp: int) -> bool:
    return any(lo <= sp <= hi for lo, hi in _RAM_RANGES)


def _fault_state(regs: dict[str, str],
                 warnings: list[str]) -> dict[str, Any] | None:
    """是否停在故障异常里。

    `IPSR` 的低 9 位（xPSR 的异常号）比读 SCB->CFSR 更直接：非 0 就是正在
    处理某个异常。**`None` 表示"没判断"，不是"没进异常"** —— 两者不能混。
    """
    val = _as_int(regs.get("xpsr"))
    if val is None:
        warnings.append("未取到 xPSR：无法判断是否停在异常里（不是「没进异常」）")
        return None
    exc_no = val & 0x1FF
    if exc_no == 0:
        return {"in_exception": False, "exception_number": 0, "exception": None}
    names = {2: "NMI", 3: "HardFault", 4: "MemManage", 5: "BusFault",
             6: "UsageFault", 11: "SVCall", 14: "PendSV", 15: "SysTick"}
    return {"in_exception": True, "exception_number": exc_no,
            "exception": names.get(exc_no, f"IRQ{exc_no - 16}" if exc_no >= 16 else None)}


# --------------------------------------------------------------------------
# 复位原因
# --------------------------------------------------------------------------

def _reset_cause(raw: int | None, warnings: list[str]) -> dict[str, Any] | None:
    if raw is None:
        warnings.append("未读到 RCC_RSR：复位原因未知")
        return None
    flags = [code for bit_name, code, _why in _RESET_PRIORITY
             if raw & (1 << _RSR_BIT[bit_name])]
    primary, why = None, None
    for bit_name, code, reason in _RESET_PRIORITY:
        if raw & (1 << _RSR_BIT[bit_name]):
            primary, why = code, reason
            break

    note = why or "RSR 全部标志为 0 —— 标志已被软件清除，本次复位源无法判定"
    if raw == RSR_POWER_ON_VALUE:
        warnings.append(
            "RCC_RSR 等于上电默认值 0x00FE0000：固件从未清过复位标志。"
            "此时 primary 只是「默认值解出来的 POR」，不代表本次复位源。"
            "要看真实原因，下次运行后清一次标志（--clear-reset-flags）再复位。")
        note = "标志未清除，读到的是上电默认值 —— 本次复位源不可判定"
    elif (raw & RSR_POWER_ON_VALUE) == RSR_POWER_ON_VALUE and primary not in ("POR",):
        # 底色还在：除 primary 之外的 PIN/POR/BOR/D1/D2/CPU 只是没清的残留，
        # 不能当成「同时发生了这么多复位」。
        warnings.append(
            f"RSR 仍含上电默认位（{', '.join(c for b, c, _ in _RESET_PRIORITY if RSR_POWER_ON_VALUE & (1 << _RSR_BIT[b]))}）；"
            f"除 primary={primary} 以外的标志可能是未清除的残留，不表示本次真的发生了。")
    return {
        "raw": f"0x{raw:08X}",
        "primary": primary,
        "flags": flags,
        "note": note,
        "flags_cleared": False,
    }


#: RSR 各标志位号（RM0433 §8.7.39）
_RSR_BIT = {
    "RMVF": 16, "CPURSTF": 17, "D1RSTF": 19, "D2RSTF": 20,
    "BORRSTF": 21, "PINRSTF": 22, "PORRSTF": 23, "SFTRSTF": 24,
    "IWDG1RSTF": 26, "WWDG1RSTF": 28, "LPWRRSTF": 30,
}


# --------------------------------------------------------------------------
# 符号
# --------------------------------------------------------------------------

def _collect_symbols(elf: str, tc: Stm32Toolchain, req: InspectRequest,
                     warnings: list[str]) -> list[dict[str, Any]]:
    """用 `nm` 把名字解析成地址；`--sym-glob` 走通配。"""
    nm = _sibling_tool(tc.gcc, "arm-none-eabi-nm")
    if not nm:
        warnings.append("arm-none-eabi-nm 未找到：符号不可用")
        return []
    try:
        r = run_text([nm, "-S", "--defined-only", elf], timeout=30)
    except Exception as exc:                       # noqa: BLE001
        warnings.append(f"nm 执行失败：{exc}")
        return []

    table: dict[str, dict[str, Any]] = {}
    for line in (r.stdout or "").splitlines():
        parts = line.split()
        if len(parts) == 4:
            addr, size, kind, name = parts
        elif len(parts) == 3:
            addr, kind, name = parts
            size = "0"
        else:
            continue
        try:
            table[name] = {"name": name, "addr": int(addr, 16),
                           "size": int(size, 16), "kind": kind}
        except ValueError:
            continue

    picked: list[dict[str, Any]] = []
    for name in req.symbols:
        if name in table:
            picked.append(table[name])
        else:
            warnings.append(f"符号 {name} 不在 ELF 的符号表里（可能被优化掉了）")
    for pat in req.sym_globs:
        hits = [v for k, v in table.items() if fnmatch.fnmatchcase(k, pat)]
        if not hits:
            warnings.append(f"--sym-glob {pat} 无命中")
        picked.extend(sorted(hits, key=lambda d: d["addr"]))

    # 去重保序
    out, seen = [], set()
    for item in picked:
        key = (item["name"], item["addr"])
        if key not in seen:
            seen.add(key)
            out.append(dict(item))
    return out


def _symbol_values(plan: list[dict[str, Any]], mem: dict[int, int],
                   req: InspectRequest) -> list[dict[str, Any]]:
    notes = _load_symbol_notes(req.symbol_notes)
    out = []
    for s in plan:
        # 每个字单独读回来的，按地址连续取 —— 数组符号也能拼出完整内容
        words: list[int] = []
        for i in range(s["words_wanted"]):
            v = mem.get(s["addr"] + 4 * i)
            if v is None:
                break
            words.append(v)
        entry: dict[str, Any] = {
            "name": s["name"],
            "addr": f"0x{s['addr']:08X}",
            "size": s["size"],
            "type": "u32" if s["size"] <= 4 else f"u32[{len(words)}]",
            "value": words[0] if words else None,
            "read_ok": bool(words),
        }
        if len(words) > 1 or s["size"] > 4:
            entry["words"] = [f"0x{w:08X}" for w in words]
        if not words:
            entry["note"] = "地址未读到（可能超出可访问范围）"
        elif notes and s["name"] in notes:
            entry["text"] = notes[s["name"]].get(words[0], notes[s["name"]].get("*"))
        out.append(entry)
    return out


def _load_symbol_notes(path: str | None) -> dict[str, dict[Any, str]]:
    """可选的符号语义表 —— 由**调用方**提供，inspect 不猜业务含义。

    格式（yaml）：`g_rsv_boot_stage: {0: 上电, 4: sup_init 之前, "*": 其它}`
    """
    if not path:
        return {}
    try:
        import yaml
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except Exception as exc:                      # noqa: BLE001
        logger.warning("符号语义表读取失败 %s: %s", path, exc)
        return {}
    out: dict[str, dict[Any, str]] = {}
    for name, table in data.items():
        if isinstance(table, dict):
            out[str(name)] = {(k if k == "*" else int(k)): str(v)
                              for k, v in table.items()}
    return out


# --------------------------------------------------------------------------
# 外设
# --------------------------------------------------------------------------

def _load_kb(board_config: dict[str, Any], warnings: list[str]):
    try:
        from firmforge.knowledge.knowledge_base import KnowledgeBase
        kb = KnowledgeBase()
        if not kb.load_for_board(board_config):
            warnings.append("寄存器知识库未加载：外设只有裸值，没有字段解码")
            return None
        return kb
    except Exception as exc:                      # noqa: BLE001
        warnings.append(f"寄存器知识库不可用：{exc}")
        return None


def _peripheral_plan(kb, names: list[str], warnings: list[str]) -> list[dict[str, Any]]:
    if not names:
        return []
    if kb is None:
        for n in names:
            warnings.append(f"--periph {n} 跳过：知识库不可用，不知道寄存器地址")
        return []

    plan = []
    for spec in names:
        spec = (spec or "").strip()
        if not spec:
            continue
        periph, _, reg = spec.partition(".")
        hits, _trunc = kb.search_registers(periph)
        if not hits:
            # SVD 里有些外设不分实例：手册写 IWDG1，库里只有 IWDG。
            # 直接报"查不到"会让人以为是工具没支持，实际是名字差一个后缀。
            alt = re.sub(r"\d+$", "", periph)
            if alt and alt != periph:
                alt_hits, _t = kb.search_registers(alt)
                if alt_hits:
                    warnings.append(
                        f"知识库里没有 {periph}，按 {alt} 读"
                        f"（该外设不分实例，手册上的实例号在 SVD 里被合并了）")
                    periph, hits = alt, alt_hits
        regs = [h for h in hits if h.get("address")]
        if reg:
            regs = [h for h in regs if str(h.get("name", "")).upper() == reg.upper()]
        if not regs:
            warnings.append(f"--periph {spec} 在知识库里查不到（外设名按数据手册写，"
                            f"如 LPTIM1 / IWDG1 / USART1）")
            continue
        if len(regs) > MAX_REGS_PER_PERIPHERAL:
            warnings.append(f"{periph} 有 {len(regs)} 个寄存器，只读前 "
                            f"{MAX_REGS_PER_PERIPHERAL} 个（--periph {spec} 可指定单个）")
            regs = regs[:MAX_REGS_PER_PERIPHERAL]
        plan.append({
            "name": periph,
            # 指定了单个寄存器时，"base" 会是那个寄存器的地址 —— 那是错的，
            # 所以宁可不给 base，也不要给一个看起来像外设基址的地址。
            "base": None if reg else _hex_of(regs[0].get("address")),
            "registers": [{
                "name": r.get("name"),
                "address": int(str(r.get("address")), 16),
                "size": int(r.get("size") or 32),
                "_fields": r.get("fields") or [],
            } for r in regs],
        })
    return plan


def _peripheral_values(plan: list[dict[str, Any]], mem: dict[int, int]) -> list[dict[str, Any]]:
    out = []
    for p in plan:
        regs_out = []
        for r in p["registers"]:
            raw = mem.get(r["address"])
            if raw is None:
                regs_out.append({"name": r["name"], "value": None,
                                 "fields": [], "read_ok": False})
                continue
            value = raw & ((1 << r["size"]) - 1 if r["size"] < 32 else 0xFFFFFFFF)
            regs_out.append({
                "name": r["name"],
                "value": f"0x{value:0{r['size'] // 4}X}",
                "fields": _decode_fields(r["_fields"], value),
                "read_ok": True,
            })
        out.append({"name": p["name"], "base": p["base"], "registers": regs_out})
    return out


def _decode_fields(fields: list[dict[str, Any]], value: int) -> list[dict[str, Any]]:
    """只输出**非零**字段 —— 一个 32 位寄存器里 20 个 0 字段会把结论淹没。"""
    out = []
    for f in fields or []:
        bit = f.get("bit")
        if bit is None:
            continue
        width = int(f.get("bit_width") or 1)
        v = (value >> int(bit)) & ((1 << width) - 1)
        if v == 0:
            continue
        out.append({"name": f.get("name"), "bit": int(bit), "width": width,
                    "value": v})
    return out


# --------------------------------------------------------------------------
# 源码位置
# --------------------------------------------------------------------------

def _location(elf: str | None, pc: int, tc: Stm32Toolchain,
              warnings: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {"pc": f"0x{pc:08X}", "function": None,
                           "file": None, "line": None}
    if not elf:
        return out
    a2l = _sibling_tool(tc.gcc, "arm-none-eabi-addr2line")
    if not a2l:
        warnings.append("arm-none-eabi-addr2line 未找到：有 PC 但没有源码行")
        return out
    # Cortex-M 是 Thumb：PC/LR 的 bit0 是状态位，不是地址的一部分。
    # 直接喂给 addr2line 会得到 "<addr>-1" 或错位一行。
    clean = pc & ~1
    try:
        r = run_text([a2l, "-f", "-C", "-e", elf, f"0x{clean:08X}"], timeout=30)
    except Exception as exc:                      # noqa: BLE001
        warnings.append(f"addr2line 执行失败：{exc}")
        return out
    lines = [ln.strip() for ln in (r.stdout or "").splitlines() if ln.strip()]
    if lines:
        out["function"] = lines[0]
    if len(lines) > 1:
        # addr2line 可能输出 `file:1261 (discriminator 1)` —— GCC 用 discriminator
        # 区分同一行内的多个位置。不剥掉就会把整串当文件名。
        loc = re.sub(r"\s*\(discriminator \d+\)\s*$", "", lines[1]).strip()
        m = re.match(r"^(.*):(\d+)(?::\d+)?$", loc)
        if m:
            out["file"] = m.group(1)
            out["line"] = int(m.group(2))
        else:
            out["file"] = loc
    if out["function"] in (None, "??") and out["file"] in (None, "??"):
        warnings.append(f"0x{clean:08X} 落在无调试信息区域（库/启动文件/汇编）")
    return out


# --------------------------------------------------------------------------
# Tcl 脚本
# --------------------------------------------------------------------------

def _build_script(req: InspectRequest, reads: list[tuple[int, int, int]],
                  *, warning_sink: list[str]) -> str:
    """生成一次性 Tcl 会话。

    每个动作都打 `FF_xxx=yyy` 标记 —— 比在 Python 里正则匹配 openocd 的打印
    格式稳（`reg` 的输出格式在 0.11→0.12 之间变过）。
    """
    parts: list[str] = [
        "# 由 ff inspect 生成 —— 一次性会话，退出前恢复现场",
        "proc ff_kv {k v} { echo \"FF_${k}=${v}\" }",
        "# 内存读数走 mrw/mrh/mrb 的**返回值**，不用 mdw：",
        "# mdw 的输出走 command_print，在 -f 脚本上下文里没有输出句柄，",
        "# 会静默什么都不打印（实测 0.12.0）。mrw 有返回值，绕开这个坑。",
        "proc ff_hex {a v} {",
        "    echo \"FF_MEM_[format 0x%08X $a]=[format 0x%08X [expr {$v & 0xFFFFFFFF}]]\"",
        "}",
        "proc ff_reg {name} {",
        "    if {[catch {set v [reg $name]} _e]} { ff_kv \"REG_${name}\" ERR }"
        " else { ff_kv \"REG_${name}\" \"${v}\" }",
        "}",
        "",
        "if {[catch {init} _e]} { echo \"FF_INIT=ERR\"; shutdown; return }",
        "ff_kv INIT OK",
        "",
        "# 进会话前的运行状态：区分「本来就停着」和「被我暂停的」",
        "set ff_prior unknown",
        "if {[info exists _TARGETNAME]} { catch {set ff_prior [$_TARGETNAME curstate]} }",
        "ff_kv PRIOR_STATE $ff_prior",
        "",
    ]

    want = 1 if req.freeze_watchdog else 0
    parts += [
        "# 看门狗冻结：**必须在 halt 之前**。",
        "# 注意：OpenOCD 的 stm32h7x.cfg 在 examine-end 里已经无条件做了",
        "#   DBGMCU_APB4FZ1 |= 0x000C0000    (bit18 IWDG1 + bit19)",
        "# 所以「默认不写」等于「保持 OpenOCD 的冻结」，--no-freeze 才是真正",
        "# 去清位 —— 否则那个开关一点作用都没有（实测过）。",
        "# 无论哪种模式，结束时都把 bit18 恢复成进入前的值，别的位不动。",
        "set ff_fz_prior NA",
        "set ff_fz_have 0",
        "set ff_fz_applied 0",
        f"if {{[catch {{set ff_fz_prior [mrw 0x{DBGMCU_APB4FZ1:08X}]}} _e] == 0}} {{",
        "    set ff_fz_have 1",
        f"    set _cur [expr {{$ff_fz_prior & 0x{IWDG1_FREEZE_BIT:08X}}}]",
        f"    if {{{want} && $_cur == 0}} {{",
        f"        if {{[catch {{mmw 0x{DBGMCU_APB4FZ1:08X} "
        f"0x{IWDG1_FREEZE_BIT:08X} 0x0}} _e] == 0}} {{ set ff_fz_applied 1 }}",
        f"    }} elseif {{!{want} && $_cur != 0}} {{",
        f"        if {{[catch {{mmw 0x{DBGMCU_APB4FZ1:08X} "
        f"0x0 0x{IWDG1_FREEZE_BIT:08X}}} _e] == 0}} {{ set ff_fz_applied 1 }}",
        "    }",
        "}",
        "ff_kv FZ_PRIOR $ff_fz_prior",
        "ff_kv FZ_APPLIED $ff_fz_applied",
        "ff_kv FZ_WANT %d" % want,
        "",
    ]

    parts += [
        "if {[catch {halt} _e]} { echo \"FF_HALT=ERR\"; echo FF_DONE=1; shutdown; return }",
        "ff_kv HALT OK",
        "# 冻结状态回读（不采信「我写过了」）",
        "set ff_fz_state NA",
        "if {[catch {set _fz [mrw 0x%08X]} _e] == 0} {" % DBGMCU_APB4FZ1,
        "    set ff_fz_state [expr {($_fz & 0x%08X) ? 1 : 0}]" % IWDG1_FREEZE_BIT,
        "}",
        "ff_kv FZ_STATE $ff_fz_state",
        "",
        "ff_reg pc",
        "ff_reg sp",
        "ff_reg lr",
        "ff_reg xpsr",
        "",
    ]

    if req.clear_reset_flags:
        parts += [
            "# 清复位标志（写 RMVF=1）。不清的话下次读到的还是这次的 sticky 位。",
            f"catch {{mmw 0x{RCC_RSR:08X} 0x{RSR_RMVF_BIT:08X} 0x0}} _e",
            "",
        ]

    for addr, count, width in reads:
        fn = {1: "mrb", 2: "mrh", 4: "mrw"}.get(width, "mrw")
        step = width if width in (1, 2, 4) else 4
        if count <= 1:
            parts.append(
                f"if {{[catch {{set _v [{fn} 0x{addr:08X}]}} _e] == 0}} "
                f"{{ ff_hex 0x{addr:08X} $_v }} else "
                f"{{ echo \"FF_MEM_0x{addr:08X}=ERR\" }}")
        else:
            parts += [
                f"set _a 0x{addr:08X}",
                f"set _n {count}",
                "for {set _i 0} {$_i < $_n} {incr _i} {",
                f"    if {{[catch {{set _v [{fn} $_a]}} _e] == 0}} "
                "{ ff_hex $_a $_v } else { echo \"FF_MEM_ERR_FROM=0x$_a\" }",
                f"    incr _a {step}",
                "}",
            ]

    parts += [
        "",
        "# 恢复：把 bit18 写回进入前的状态，其余位一律不动",
        "if {$ff_fz_applied == 1 && $ff_fz_have == 1} {",
        f"    set _restore [expr {{($ff_fz_prior & 0x{IWDG1_FREEZE_BIT:08X}) ? 0x{IWDG1_FREEZE_BIT:08X} : 0x0}}]",
        f"    catch {{mmw 0x{DBGMCU_APB4FZ1:08X} $_restore 0x{IWDG1_FREEZE_BIT:08X}}} _e",
        "}",
        "ff_kv FZ_RESTORED [expr {$ff_fz_applied == 1 ? 1 : 0}]",
    ]
    if req.resume:
        parts += ["catch {resume} _e", "ff_kv RESUMED 1"]
    else:
        parts += ["ff_kv RESUMED 0"]

    parts += ["echo FF_DONE=1", "shutdown", ""]
    return "\n".join(parts)


# --------------------------------------------------------------------------
# 解析
# --------------------------------------------------------------------------

def _parse_markers(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in text.splitlines():
        m = _MARKER_RE.match(raw.strip())
        if m:
            out[m.group(1)] = m.group(2).strip()
    return out


def _parse_mem(markers: dict[str, str]) -> dict[int, int]:
    """把 `FF_MEM_0x<addr>=0x<value>` 标记行收成 地址 → 值。

    数据源是 `mrw` 的**返回值**（经 `ff_hex` 打印），不是 `mdw` 的输出：
    `mdw` 在 `-f` 脚本里没有输出句柄，会静默什么都不打印。
    """
    out: dict[int, int] = {}
    for key, val in markers.items():
        m = _MEM_MARK_RE.match(key)
        if not m:
            continue
        v = _as_int(val)
        if v is not None:
            out[int(m.group(1), 16)] = v
    return out


def _as_int(value: str | None) -> int | None:
    """从一段文本里取数值。

    `reg` 的返回值在 openocd 0.12 是 `pc (/32): 0x08003A58`（带前缀），
    别的版本可能只给裸数字。判定规则：

    * 有 `0x` 前缀       → 十六进制；
    * 纯数字 token       → **十进制**（openocd 的 Tcl 数值默认按十进制印）；
    * 含 a-f 的无前缀串  → 十六进制。
    """
    if not value or value in ("ERR", "NA"):
        return None
    text = value.rsplit(":", 1)[1] if ":" in value else value
    parts = text.split()
    if not parts:
        return None
    tok = parts[0].strip(",;()")
    try:
        if tok.lower().startswith("0x"):
            return int(tok, 16)
        if tok.isdigit():
            return int(tok, 10)
        if all(c in "0123456789abcdefABCDEF" for c in tok):
            return int(tok, 16)
    except ValueError:
        return None
    return None


def _hex(value: str | None) -> str | None:
    v = _as_int(value)
    return f"0x{v:08X}" if v is not None else None


def _hex_of(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return f"0x{int(str(value), 16):08X}"
    except ValueError:
        return str(value)


# --------------------------------------------------------------------------
# ELF / 工具
# --------------------------------------------------------------------------

def _elf_candidates(root: Path) -> list[Path]:
    """构建缓存里的全部 ELF，最新在前。"""
    return sorted(root.glob("*/firmware.elf"),
                  key=lambda p: p.stat().st_mtime, reverse=True)


def _describe_elf(p: Path) -> str:
    """候选清单的一行：应用名、大小、时间。缺一个都判断不出该选谁。"""
    try:
        st = p.stat()
    except OSError:
        return f"  {p.parent.name}  ({p})"
    return (f"  --app {p.parent.name:<20s} "
            f"{st.st_size:>7d} B  "
            f"{datetime.datetime.fromtimestamp(st.st_mtime):%Y-%m-%d %H:%M:%S}")


def _resolve_elf(board_config: dict[str, Any], req: InspectRequest,
                 warnings: list[str]) -> tuple[str | None, str]:
    if req.elf and req.app:
        raise InspectError("--elf 与 --app 只能给一个（两者都指向 ELF，给两个无法判断以谁为准）")

    if req.elf:
        p = Path(req.elf)
        if p.is_file():
            return str(p), ""
        raise InspectError(f"--elf 指向的文件不存在：{req.elf}")

    board_id = board_config.get("board_id") or ""
    try:
        from firmforge.infrastructure import paths
        root = paths.build_cache_dir() / board_id
    except Exception:                             # noqa: BLE001
        return None, "拿不到构建缓存目录"
    if not root.is_dir():
        return None, f"构建缓存里没有 {board_id}（先 ff build）"

    if req.app:
        p = root / req.app / "firmware.elf"
        if p.is_file():
            return str(p), ""
        avail = [x.parent.name for x in _elf_candidates(root)]
        raise InspectError(
            f"--app {req.app} 在构建缓存里没有 firmware.elf：{p}",
            candidates=[f"可用：{', '.join(avail) or '（无）'}"],
            hint=f"先 ff build {board_id} --app {req.app}，或换个 --app")

    hits = _elf_candidates(root)
    if not hits:
        return None, f"{root} 下没有 firmware.elf（先 ff build）"
    if len(hits) > 1:
        # 多份时**拒绝猜测**。曾经按 mtime 取最新，在 app/ 与
        # hello_blink/ 并存时选中了 hello_blink 的 ELF —— 于是
        # `Where:` 打印出一个完全合理但属于另一个固件的函数名。
        # 这比直接报错危险得多：错的答案看起来是对的，不会有人去查。
        # mtime 也证明不了「是不是这份源码编的」：拷文件、解压、
        # 单独 build 别的项目都会刷新它。
        raise InspectError(
            f"构建缓存里有 {len(hits)} 份 firmware.elf，无法判断你要看哪一份："
            f"\n" + "\n".join(_describe_elf(p) for p in hits),
            candidates=[f"用 --app <应用名> 指定，或 --elf <路径> 直接给文件"],
            hint=f"目录 {root} 是跨项目共享的，不按修改时间猜")
    return str(hits[0]), ""


def _sibling_tool(gcc: str, name: str) -> str | None:
    """与 gcc 同目录的兄弟工具（nm / addr2line）—— 避免再走一遍 PATH 探测。"""
    if gcc:
        p = Path(gcc).parent / (name + (".exe" if gcc.lower().endswith(".exe") else ""))
        if p.is_file():
            return str(p)
    return None


__all__ = ["inspect", "InspectRequest", "InspectError", "SCHEMA",
           "DBGMCU_APB4FZ1", "IWDG1_FREEZE_BIT", "RCC_RSR", "RSR_POWER_ON_VALUE"]
