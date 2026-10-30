# 终端 Widget · Agent 使用文档

简介：用户与 Agent 共享可见终端。Widget ID 为 `terminal`；每个终端 ID 形如 `terminal-ID-xxxxxxxxxxxx`。

## 用户附加的终端

用户在终端列表右键选择“附加到当前聊天中”，聊天中会出现：

> 用户附带了来自widget：terminal-ID-xxxxxxxxxxxx的终端

英文界面使用对应英文提示。这个引用指向终端插件中的已有进程。先 `umeko_desktop widgets.docs`，参数 `{"id":"terminal"}`，再通过 `widgets.call` 操作它。不要把 `terminal-ID-...` 当成 Widget 包 ID，也不要另外创建一个 Shell 代替用户附加的终端。

只有用户已附加到本聊天的终端才允许 Agent 访问；`list` 仅返回这些终端。其他聊天、猜测 ID、终端已关闭或工作区已改变时会被拒绝，需要用户重新附加。

## 公开方法

| 方法 | 参数 | 结果 |
| --- | --- | --- |
| `list` | `{}` | 本聊天可操作的终端 ID、名称、Shell、工作目录和运行状态 |
| `read` | `terminalId`，可选 `lines`（1–1000，默认 200）、`afterSequence` | 已解析的屏幕及历史文本、最新 `sequence`、截断标志；序号未变时 `changed:false` |
| `run` | `terminalId`、`command` | 在这个终端输入命令并回车，返回 `submitted:true` 和 `afterSequence` |
| `write` | `terminalId`、`text` | 发送原始交互输入；回车为 `\r`，退出/控制键按终端协议发送 |
| `interrupt` | `terminalId` | 发送 Ctrl+C 中断当前前台命令 |

```json
{"operation":"widgets.call","arguments":{"id":"terminal","method":"read","arguments":{"terminalId":"terminal-ID-xxxxxxxxxxxx","lines":100}}}
```

方法调用返回 `accepted`、`requestId`，再以 `widgets.result` 读取 `completed` 或 `failed` 的实际 RPC 结果。`run` 的 `completed` 仅表示命令已写入终端，**不代表 Shell 命令执行结束或成功**。使用 `read` 检查真实输出、程序交互提示和 Shell 提示符；不要伪造退出码。`exitCode` 仅代表终端 Shell 进程退出，不是最近命令的退出码。

## 可见性与生命周期

Agent 执行时会请求打开终端页面并选择目标终端，前台用户能直接看到命令和输出；在别的聊天后台执行时不会抢占当前用户的面板。需要显式展示时可使用 `widgets.open`，参数 `{"id":"terminal"}`。

终端采用应用级生命周期。面板收起及切换聊天后进程继续运行；关闭终端、停用/卸载插件或退出应用后终端失效。所有操作都在同一 PTY 内执行，先检查 Shell 和 `cwd`，不要假设是当前聊天的默认目录。共享终端中的现有环境、程序和任务应遵循用户意图处理。

返回的 `cwd` 标记 `cwdKind: "initial"`，表示启动目录。用户可能已经在 Shell 中切换目录；需要实际目录时，在同一终端运行 `Get-Location`（PowerShell）、`cd`（cmd）或 `pwd`（POSIX）并读取结果。
