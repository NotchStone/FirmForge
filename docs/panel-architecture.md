# 串口面板 + Modbus 面板架构

> 更新：2026-08-18
> 核心约束：**物理串口唯一** → 只能一个采集线程(collector)

## 一、三文件分层

```
┌─ firmforge/tools/panel.html ──────────────── 表示层
│  一个文件, 两个标签(Serial/Modbus), 共用串口控制栏
├─ firmforge/adapters/panel_service.py ─────── 服务层
│  HTTP 路由层, 独立服务(9878-9887 端口回退), 仅面板相关路由
├─ firmforge/core/pipeline_runner.py ────────── 采集层
│  _collector_thread 唯一串口读写线程
```

### 1.1 panel.html (表示层)

单文件双标签架构。Serial 标签和 Modbus 标签共用顶栏串口参数：

```
[dot] FirmForge | COM4 | 9600 | 8N1 | Clear | Close
  └── port, baud, parity, Open/Close, Clear, RX/TX 计数
Serial | Modbus                          RX: n  TX: n
```

**Serial 标签职责：**
- 连续串口数据显示（SSE 推送）
- 发送栏：自由格式文本/HEX 写入 + CRLF 开关
- 自动滚底、Clear 按标签区分

**Modbus 标签职责：**
- 时间线模式：TX→ / RX← 双毫秒时间戳左置 / 解码网格
- 前端 JS 完成 Modbus RTU 帧组装 + CRC-16 显示
- 点击 Send → POST `/modbus` → Queue IPC → collector 原子执行 → 响应回队列
- 实际发送帧由后端 `modbus_encode_frame` 重建（前端拼帧仅用于显示）

**共用项（两个标签共享）：**
- 串口控制栏：端口、波特率、校验位(8N1/8E1/8O1)、Open/Close、Clear
- RX/TX 计数（Modbus 页使用独立 JS 变量 `mbRx/mbTx`，不受 SSE 覆盖）
- 阶段状态行 (stages) / 过程信息行 (process)

### 1.2 panel_service.py (服务层)

从 mcp_server.py 拆出的独立 HTTP 服务，端口 9878-9887 回退。
包含的面板路由：

| 路由 | 方法 | 功能 |
|------|------|------|
| `/serial_live.html` | GET | 返回面板 HTML |
| `/stream` | GET | SSE 数据流（3s 心跳，断连不杀 collector） |
| `/serial-send` | POST | 普通串口写入(serial_write.json) |
| `/serial-config` | POST | 波特率/校验位配置(serial_config.json) |
| `/modbus` | POST | Modbus 命令（Queue IPC，5s 超时返回 ok:False） |
| `/serial-open` | POST | 打开串口(移除 .pause) |
| `/serial-close` | POST | 关闭串口(创建 .pause) |
| `/serial-stop` | POST | 停止采集(创建 .stop + .pause) |
| `/quit` | POST | 优雅关闭面板服务(collector 停止 + httpd shutdown) |

**Modbus 队列 IPC（2026-08-14 迁移，替代原文件管道）：**
- `get_modbus_request_queue()` / `get_modbus_response_queue()` 两个 `queue.Queue`
- HTTP handler: `req_q.put(data)` → `resp_q.get(timeout=5)`
- collector: `req_q.get(block=False)` → 执行 → `resp_q.put(...)`
- 延迟 ~60-100ms（原文件轮询 ~500-900ms）

### 1.3 pipeline_runner.py (采集层)

_collector_thread 是唯一串口读写线程，主循环：

```python
while True:
    if 发现 .stop:   break                # 停止采集
    if 发现 .pause:  关闭 COM4 等待重开     # Close 按钮
                     (重开时读 serial_config.json 更新 baud/parity)
    if serial_write.json: 串口写入         # 普通发送
    _exec_modbus(ser, tx_total, rx_total) # Modbus 原子操作(Queue IPC)
    ser.read(64) → SSE → HTML            # 持续采集
```

**核心原则：** Modbus 的收发是原子操作（读队列 → 拼帧 → 发 → 阻塞读 → 回队列），期间主线采集暂停，响应不会被主循环抢读。

**波特率/校验位配置链路：**
面板 baudsel/paritysel onchange → `POST /serial-config` → `serial_config.json` → collector 重开串口时读取 → `ComPort(port, baud, parity=parity)` → Win32Serial `_build_dcb(baud, parity)` 设置 DCB。

## 二、Modbus 交互流程（Queue IPC）

```
panel.js                     panel_service.py             collector thread
──────                       ────────────────             ────────────────
拼帧+CRC(仅显示 TX→)                                                │
  │                                                                │
  ├── POST /modbus ───────────►                                    │
  │                        req_q.put(data)                          │
  │                        resp_q.get(timeout=5)                    │
  │                              │                          req_q.get(block=False)
  │                              │                          modbus_encode_frame()
  │                              │                          ser.write(frame)
  │                              │                          ser.read(256) 阻塞读
  │                              │                          resp_q.put({raw,regs,...})
  │                              │◄────────────────────────
  │                         读到 resp                           │
  │◄──────── 返回 {ok, raw, rx, tx} ──────                        │
  │                                                                │
渲染 RX← + 解码网格 + mbRx/mbTx 累加                                │
```

## 三、文件职责边界

### 不动 pipeline_runner.py 原则

`_exec_modbus` 不可修改的内容：
- 串口读/写/CRC 校验逻辑
- Modbus 帧结构（由 `modbus_utils.modbus_encode_frame` 生成，四功能码分帧）
- 采集循环主结构

可修改（只调表现，不调逻辑）：
- 超时时间（当前 50ms 等待 + 阻塞读 300ms）
- 错误处理（ser=None 时回明确错误而非超时）

### 不动 mcp_server.py 原则

面板路由已从 mcp_server.py 迁移到 panel_service.py，mcp_server.py 不再新增面板相关功能。`_get_stream_queue` 由 mcp_server 转发到 panel_service 保持兼容。

### 只动 panel.html 原则

调试 Modbus 面板 UI 时，所有修改限于 panel.html：
- 时间线布局
- 表单控件
- JS 拼帧/CRC/解码逻辑（显示层）
- 发送数据格式

## 四、功能状态（2026-08-18）

| 功能 | 状态 |
|------|------|
| Serial/Modbus 双标签独立 | ✅ |
| ASCII/HEX/CRLF 发送 | ✅ |
| Modbus FC03/04/06/16 拼帧（后端重建） | ✅ FC06 已修复（原多 0x0000 字） |
| Modbus 解码网格 + 异常响应解码 | ✅ |
| RX/TX 计数器（Modbus 独立变量） | ✅ |
| 波特率/校验位配置生效 | ✅ 2026-08-18（原死控件） |
| SSE 相对路径（端口回退兼容） | ✅ 2026-08-18（原硬编码 9878） |
| Clear 按标签 + 计数器归零 | ✅ |
| 串口关闭时 Modbus 明确报错 | ✅ 2026-08-18 |
| Open/Close 刷新状态真实反映 | ✅ 2026-08-18 |
| /quit 优雅退出 | ✅ 2026-08-18（原 os._exit 杀进程） |

## 五、测试

- `tests/test_modbus_utils.py`：CRC / encode_frame 四功能码 / decode_response
- `tests/test_panel_service.py`：HTTP 路由（serial-send/config/close/open/modbus）
- `tests/test_exec_modbus.py`：mock serial 测拼帧/解码/ser=None
- `tests/test_collector_baud.py`：serial_config.json 读取
