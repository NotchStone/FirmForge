# FirmForge × DeepSeek Harness — Cordis 插件集成方案（v2）

> 日期：2026-08-20 | 状态：方案论证完成，待实施
> 论证基线：dsh 官方源码 `deepseek-ai/deepseek-harness@0.1.0-rc.8`（`C:\MyLab\DSH-FF\`）+ FirmForge v3.1 项目现状

---

## 一、论证基线

### 1.1 dsh 侧事实（源码级，`docs/cookbook/adding-a-tool.md` + `packages/core/tools/src/schema.ts`）

| 契约 | 源码事实 |
|:--|:--|
| 工具注册 | `ctx.tools.register(defineTool({...}))`，注册基于 effect（插件卸载自动注销） |
| `defineTool` 字段 | `name`（唯一）、`description`、`parameters`（隐式开放对象根）、`output{schema, render, presentationMeta?}`、`timeoutMs?`、`isConcurrencySafe?`、`execute(args, exec)`、`finalizeContent?`、`presentCall?`、`presentResult?` |
| 参数校验 | `parameterSchemaSpecToJsonSchema` 编译 → execute 前 `validate`，违规抛 `ToolArgsError` |
| execute 返回值 | 只返回规范 JSON 值（`ValueSchemaSpec`），registry 快照/校验/冻结 → `output.render`；抛异常 = isError |
| 取消 | `exec.signal`（`ToolRunContext extends ToolExecution`），取消时须中止进行中工作 |
| 长任务 | `ctx.jobs.start({kind, label, owner, run})`：producer 提供同步 `cancel`、非拒绝 `done`、可选 `readOutput`；jobId 发布后用 task-owned 信号 |
| 策略扩展点 | `tools/pre-execute`（allow/deny/ask）、`ctx.tools.guard()`（单调拒绝）、`tools/execute`（deadline/retry）、`tools/post-execute`、`tools/result` |
| UI | `output.render`（模型内容）+ `presentCall/presentResult`（generic/terminal/diff/search/web 卡，纯函数，replay 安全） |
| Code Mode | 注册工具自动可用：`await tools.<name>(args)`，类型从 schema 推导 |
| 通知 | `exec.agent.inject({content, source:{kind:'plugin', plugin}})` 注入下轮上下文 |
| 分发 | package.json 声明 `"dsh": {"bundle": ...}` 自动进 bundle 层；`dsh plugin add <path|github:...>` |
| 环境 | Node ^22.19/≥24、pnpm、`DEEPSEEK_API_KEY` |

### 1.2 FirmForge 侧现状

| 资产 | 说明 |
|:--|:--|
| 五阶段管道 | Detect → Review → Build → Flash → Verify（`pipeline_runner.py`，可 import） |
| MCP 6 工具 | `ff_detect/ff_context/ff_build/ff_run/ff_flash/ff_monitor`，`TOOL_SCHEMAS`（JSON Schema）可复用 |
| CLI 5 命令 | `ff detect/build/run/flash/setup` |
| 串口层 | `ComPort`（Win32Serial 优先 + pyserial 兜底 + clean_close 自愈） |
| 硬件 | ATmega2560/328P（UNO/Nano/Mega），真实编译/烧录/串口验证 |
| 包 | Python ≥3.10，包内数据 `firmforge/data/`（cwd 无关） |
| 缺陷（对插件） | **CLI 无 `--json` 机器可读输出**；无 `ff context` 子命令（Phase A 待做） |

---

## 二、接入决策论证

### 2.1 原生 Cordis 插件 vs MCP 桥接

| 维度 | 原生 Cordis 插件 | MCP 桥接（dsh mcp-client） |
|:--|:--|:--|
| 工具身份 | dsh 一等公民（`ctx.tools.register`） | 经 mcp-client 发现/注册（`packages/mcp/mcp-client/src/tools.ts`） |
| 长任务 | ✅ `ctx.jobs` 全量能力 | 受限（MCP 层无 jobs 语义，需自行映射） |
| 策略扩展点 | ✅ `tools/pre-execute` 等 | 受限 |
| UI 卡 | ✅ presentCall/presentResult | 受限（MCP 工具走 generic 回退） |
| Code Mode | ✅ 免费可达 | 需经 MCP 桥 |
| schema 控制 | 完全自控 | 经 MCP 转换层 |
| 热插拔 | ✅ effect 可逆 | 桥接插件自身可热插拔，但工具语义降级 |
| 实现成本 | 中（~5 工具 + runtime） | 低（配置即用） |

**结论**：原生插件在 dsh 架构中享有完整能力（jobs/effect/policy/UI），MCP 桥接是"配置即用"的低配路径。FirmForge 的 `ff_run`（烧录+串口验证，秒级长任务）与 `ff_flash` 天然需要 jobs 语义——**原生插件为唯一合理选择**。MCP 桥接仅作为验证 dsh 生态的临时探针。

### 2.2 进程通信：常驻进程内核

| 方案 | 延迟 | 状态保持 | 复杂度 |
|:--|:--|:--|:--|
| 每次 spawn CLI | 300-800ms/次 | 无 | 低 |
| **常驻进程（选定）** | ~5ms/次 | ✅（串口/缓存可保持） | 中 |
| TS 重写 | ~1ms | ✅ | 高（不采用：178 tests 硬件坑重踩） |

**选定**：插件 mount 时 `ctx.effect` 内 spawn 常驻 firmforge 进程（`python -m firmforge.adapters.cli <cmd> --json`，stdin 命令循环）；unmount 时终止进程 + 串口 `clean_close` 释放。

---

## 三、工具集设计（defineTool × 5）

### 3.1 工具清单与同步/后台划分

| 工具 | 执行方式 | 说明 |
|:--|:--|:--|
| `ff_detect` | 同步 execute | 板卡识别，毫秒级 |
| `ff_context` | 同步 execute | 寄存器/引脚/波特率参考，毫秒级 |
| `ff_build` | 后台 jobs | 编译（秒级，含 core 缓存） |
| `ff_run` | 后台 jobs | 全链路（秒-分钟级：烧录+串口验证） |
| `ff_flash` | 后台 jobs | 直烧（秒级） |

### 3.2 defineTool 定义规范（以 ff_run 为例）

```ts
ctx.tools.register(defineTool({
  name: 'ff_run',
  description: 'Compile, flash and verify firmware on real hardware (5-stage pipeline). '
    + 'Requires a board connected. Returns pipeline result with stages.',
  parameters: {
    board: { type: 'string', description: 'Board ID (arduino_mega / arduino_328p)' },
    app:   { type: 'string', required: true, description: 'Absolute path to source directory' },
    expected: { type: 'string', description: 'Serial output regex to match (optional)' },
  },
  output: {
    schema: {
      type: 'object',
      properties: {
        success: { type: 'boolean' },
        board: { type: 'string' },
        stages: { type: 'array', items: { type: 'object' } },
        total_elapsed_ms: { type: 'number' },
      },
      required: ['success', 'board'],
    },
    render: (_args, value) => [{ type: 'text',
      text: `ff_run ${value.success ? 'PASS' : 'FAIL'} | board=${value.board} | ${value.stages?.length ?? 0} stages` }],
  },
  timeoutMs: 0,          // 0/omit = no tool-level budget; jobs own the lifecycle
  async execute(args, exec) {
    // jobs.start: 后台任务（发布 jobId 后由 job_kill 管理）
    return ctx.jobs.start({
      kind: 'firmforge/ff-run',
      label: `ff-run ${args.app}`,
      owner: exec.agent,
      run: async (task) => runtime.ffRun(args, task.signal),  // task-owned 信号
      cancel: () => runtime.cancel(),
      done: () => runtime.cleanup(),
      readOutput: () => runtime.tail(),
    })
  },
}))
```

### 3.3 execute 契约落实（全部工具统一）

1. **只返回规范 JSON 值**：每个工具输出 `{success, ...}` 对象（design as programmatic API，human prose 放 render）
2. **错误语义**：基础设施失败抛异常（=isError）；领域失败（编译错误/烧录失败/板未接）放进规范值 `{success:false, error, stderr}`——模型可读可判断
3. **遵守 exec.signal / task.signal**：取消 → kill 子进程（runtime.ts）
4. **注册后 schema 只读**：热替换 = dispose effect 重注册（不 mutate）

---

## 四、运行时设计（runtime.ts）

```ts
// 常驻 firmforge 进程（--json 命令循环）
class FirmForgeRuntime {
  private proc: ChildProcess           // spawn: python -m firmforge.adapters.cli --json-mode
  private queue: PendingCall[]         // 请求队列（单进程串行，硬件操作天然串行）
  mount(): void                        // ctx.effect 中调用：spawn + 健康检查（ff --version）
  call(cmd, args, signal): Promise<JsonValue>  // 写入 stdin 命令 → 读 stdout JSON → resolve
  cancel(): void                       // 终止当前执行中的子进程操作
  cleanup(): void                      // 终止进程 + com_port_clean_close(port) 释放串口
}
```

要点：
- **串行语义**：硬件操作（烧录/串口）天然互斥，命令队列串行执行，避免并发串口冲突
- **信号**：`signal.addEventListener('abort')` → `proc.kill()` + 队列清理
- **健康**：mount 时 `ff --version` 探活；进程崩溃自动重启（退避）
- **配置**：`pythonPath`、`boardsDir` 可配（插件 Config）

---

## 五、生命周期与热插拔（dsh 标准达标）

```
mount（插件 apply）
├─ ctx.effect(() => {
│    runtime.mount()                    // spawn 常驻进程
│    return () => {                     // unmount / HMR / 关停 自动执行
│      runtime.cleanup()                // 终止进程
│      com_port_clean_close(port)       // 释放串口（重装无 COM 冲突）
│    }
│  })
├─ ctx.tools.register(...) × 5          // effect-based，卸载自动注销
└─ ctx.on('tools/pre-execute', ...)     // 策略钩子（可选）
```

**热插拔达标**：全部注册/副作用经 `ctx.effect`，框架保证卸载回滚；唯一硬要求是**串口释放**放在 cleanup 中（`clean_close` 1200→9600 toggle 已验证可靠）。

---

## 六、策略与安全（可选增强，Phase D 后）

- `tools/pre-execute`：`ff_flash` 触发前 ask 确认（烧录是破坏性操作）——策略不进工具，符合 dsh 规范
- `ctx.tools.guard()`：最终单调拒绝（如 `app` 路径必须绝对路径）
- 权限模型：插件 Config 提供 `allowFlash: boolean`，由部署配置门控

---

## 七、UI 呈现

| 工具 | presentCall | presentResult |
|:--|:--|:--|
| ff_detect | generic（板卡列表） | generic |
| ff_context | generic | generic |
| ff_build | generic（编译中） | generic（success/errors） |
| ff_run | **terminal 卡**（烧录输出） | terminal（串口样本） |
| ff_flash | **terminal 卡**（avrdude 输出） | terminal |

纯函数约束：present 侧不 I/O、不读会话状态（replay 安全）。

---

## 八、分发与安装

- `package.json`：`{"dsh": {"bundle": "cordis.yml"}}` → 自动进 profile bundle 层
- 发布：npm 包 + GitHub 仓库（topic: `dsh-plugin`）
- 安装：`dsh plugin --profile <name> add github:NotchStone/dsh-plugin-firmforge`
- 依赖：`@deepseek-ai/dsh-tools`（工具定义）、`@deepseek-ai/cordis`（类型）

---

## 九、Phase 实施计划

| Phase | 内容 | 产出 | 验证 |
|:--|:--|:--|:--|
| **A**（FirmForge 主仓） | CLI `--json` + `ff context` 子命令 + `test_cli_json.py` | firmforge 0.3.0 | pytest 全绿 |
| **B** | `npx @deepseek-ai/dsh web` 环境验证 + 锁版本（rc.8） | 运行截图 | 手动 |
| **C** | 插件脚手架：ff_detect 单工具（同步 execute）+ runtime 雏形 | 插件可安装 | dsh 中调用 ff_detect |
| **D** | 全 5 工具 + jobs 后台任务 + effect 生命周期 + 串口释放 | 完整插件 | dsh 中 ff_run/ff_flash |
| **E** | Mega2560 真实硬件端到端 + 热插拔验证（卸载/重装） | 验证报告 | 硬件全链路 |

---

## 十、风险与缓解

| 风险 | 缓解 |
|:--|:--|
| dsh v0.1 破坏性变更（官方明示） | 锁版本 `0.1.0-rc.8`；升级前读 changelog |
| 常驻进程串口占用冲突（面板/ff 同时用） | 串行队列 + cleanup 释放；文档说明"同一时间一个 ff 客户端" |
| ff CLI 无 --json（Phase A 前） | Phase A 先行，插件依赖该接口 |
| Windows Python 子进程路径 | runtime Config 提供 `pythonPath`（默认 python） |
| 长任务（ff_run）超 30s | jobs 后台任务（job_output/job_kill），不阻塞 agent |
| 模型幻觉传参（app 路径不存在等） | defineTool 参数校验 + 规范错误值 `{success:false,error}` 返回模型 |

---

## 附录：与 MCP 的关系

- FirmForge MCP server（`ff_detect/.../ff_monitor` 6 工具）**保持现状**——服务 CodeBuddy/Cursor/Claude 等 MCP 客户端
- Cordis 插件（本方案）服务 DeepSeek Harness——**新分发形态，不替代 MCP**
- 两者共享同一 PipelineRunner 与 TOOL_SCHEMAS，同一套验证引擎，两个壳
