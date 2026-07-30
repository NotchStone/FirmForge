# 串口面板 + Modbus 面板架构

> 更新：2026-07-30
> 核心约束：**物理串口唯一** → 只能一个采集线程(collector)

## 一、三文件分层

```
┌─ firmforge/tools/panel.html ──────────────── 表示层
│  一个文件, 两个标签(Serial/MODBUS), 共用串口控制栏
├─ firmforge/adapters/panel_service.py ─────── 服务层
│  HTTP 路由层, 独立服务, 仅面板相关路由
├─ firmforge/core/pipeline_runner.py ────────── 采集层
│  _collector_thread 唯一串口读写线程
```

### 1.1 panel.html (表示层)

单文件双标签架构。Serial 标签和 MODBUS 标签共用顶栏串口参数：

```
[dot] FirmForge | COM4 | 9600 | 8N1 | None | Clear | Close
  └── port, baud, Open/Close, Clear, RX/TX 计数均共用
```

**Serial 标签职责：**
- 连续串口数据显示（SSE 推送）
- 发送栏：自由格式文本/HEX 写入
- 自动滚底、HEX 模式切换、换行模式切换

**MODBUS 标签职责：**
- 时间线模式：TX→ / RX← / 解码网格
- 前端 JS 完成 Modbus RTU 帧组装 + CRC-16 ��验
- 点击 Send → POST `/modbus` → 后端写 modbus_cmd.json → collector 轮询执行
- 响应回读: 后端轮询 modbus_resp.json → 前端渲染时间线

**共用项（两个标签共享）：**
- 串口控制栏：端口、波特率、帧格式、校验位、Open/Close、Clear
- RX/TX 计数值
- 阶段状态行 (stages)
- 时间戳

### 1.2 panel_service.py (服务层)

从 mcp_server.py 拆出的独立 HTTP 服务，运行在 9878 端口。
包含的面板路由：

| 路由 | 方法 | 功能 |
|------|------|------|
| `/serial-live.html` | GET | 返回面板 HTML |
| `/send` | POST | 普通串口写入(send_cmd.json) |
| `/modbus` | POST | Modbus 命令(写 cmd + 轮询 resp) |
| `/stream` | GET | SSE 数据流 |
| `/open` | POST | 打开串口(移除 .pause) |
| `/close` | POST | 关闭串口(创建 .pause) |
| `/stop` | POST | 停止采集(创建 .stop) |

不包含 MCP 工具路由（ff_detect / ff_build / ff_context 等留存于 mcp_server.py）。

### 1.3 pipeline_runner.py (采集层)

_collector_thread 是唯一串口读写线程，主循环：

```python
while True:
    if 发现 .stop:   break           # 停止采集
    if 发现 .pause:  关闭 COM4 等待    # 关闭串口
    if send_cmd.json: 串口写入        # 普通发送
    if modbus_cmd.json:               # Modbus 原子操作
        ser.write(frame)              # 发送
        ser.read(256)                 # 阻塞读响应(300ms timeout)
        写 modbus_resp.json           # 回写
    ser.read(64) → SSE → HTML        # 持续采集
```

**核心原则：** Modbus 的收发是原子操作（清缓冲 → 发 → 收 → 写响应），期间主线采集暂停，响应不会被主循环抢读。

## 二、Modbus 交互流程

```
panel.js                         panel_service.py             collector thread
──────                           ────────────────             ────────────────
拼帧+CRC(TX→)                                                        │
  │                                                                  │
  ├── POST /modbus ──────────►                                      │
  │                        写 modbus_cmd.json                        │
  │                        轮询 modbus_resp.json                     │
  │                              │                            循环发现 cmd
  │                              │                            ser.write(frame)
  │                              │                            ser.read(256)
  │                              │                            写 resp.json
  │                              │◄──────────────────────────
  │                         读到 resp.json                       │
  │                              │                              │
  │◄──────── 返回 raw/regs ──────                              │
  │                                                                  │
渲染 RX← + 解码网格                                                   │
```

## 三、文件职责边界

### 不动 pipeline_runner.py 原则

`_process_modbus_file` 不可修改的内容：
- 串口读/写/CRC 校验逻辑
- 文件管道接口（modbus_cmd.json / modbus_resp.json 格式）
- 采集循环主结构

可修改（只调表现，不调逻辑）：
- 读取策略：轮询 → 阻塞读（当前问题）
- 超时时间
- 错误处理

### 不动 mcp_server.py 原则

面板路由最终从 mcp_server.py 迁移到 panel_service.py 后，mcp_server.py 不再新增面板相关功能。

### 只动 panel.html 原则

调试 Modbus 面板 UI 时，所有修改限于 panel.html：
- 时间线布局
- 表单控件
- JS 拼帧/CRC/解码逻辑
- 发送数据格式

后端文件管道的输入/输出格式定义清楚后固化，不改。

## 四、当前问题

| 问题 | 状态 | 原因 | 方案 |
|------|------|------|------|
| RX← (no response) | 未解决 | 采集线程主循环抢走 Modbus 应答 | _process_modbus_file 改用阻塞 ser.read(256) |
| 时间戳粘合 | 已解决 | 前次修复 | panel.html 添加 flex gap |
| CRC ERR | 未验证 | 响应为空导致 | 等 RX← 正常后再看 |

## 五、改造计划

1. ✅ UI 面板三层布局定稿
2. ✅ 阶段图标分级
3. ✅ S2 阻断规则
4. ✅ Modbus 时间线页面（前端）
5. ✅ Modbus 从站固件烧录验证
6. ❌ Modbus RX← 回读修复
7. ❌ panel_service.py 从 mcp_server.py 拆分
8. ❌ Modbus 交互全链路调通
