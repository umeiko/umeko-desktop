# 会话任务服务

这是无页面的应用常驻插件。启用后，它在后台线程取得独立的原生会话，提交配置里的 `content`，等待真实终态，并把最近结果写入 `context.state_dir/latest-task.json`。`status` 返回同一结果。任务在后台独立运行，前台聊天和输入框保持不变。

由用户编辑当前或隔离应用 profile 的 `settings.json`，在**顶层**添加 `pluginSessionProfiles` 来批准配置（新建配置通过编辑文件完成；应用运行时编辑的内容会在下一次保存设置时读入）。已有配置的模型可以在“设置 → Agent → 插件会话模型”中随时更换。示例值需要替换为已存在的工作区、桌面模型别名和 Provider ID：

```json
{
  "pluginSessionProfiles": {
    "session-task-service": {
      "tasks": {
        "workspace": "/path/to/workspace",
        "model": "test-model",
        "provider": "Test provider",
        "tools": [],
        "permissionMode": "ask",
        "allowApprovals": false
      }
    }
  }
}
```

插件配置的 `profile` 默认是 `tasks`。`model` 填现有桌面模型别名（上游模型名称在这里无效）；可选 `provider` 填已配置的 Provider ID，宿主会核对该别名确实路由到这个 Provider。两个 Provider 的别名冲突时，使用唯一别名。

插件按名称选择宿主已批准的配置，工作目录、模型和工具都由配置决定。工具与权限还受桌面策略限制。服务始终排除 `umeko_desktop`、`pi` 和 `pi_commands` 这些桌面管理工具，写入 `tools` 也不会生效。其他核心工具及可选子 Agent 工具在显式配置且桌面策略允许时可用。子 Agent 运行时继承同一强制工具与权限上限，模型注册表只提供配置选定的模型。此示例不注册审批处理器，需要审批时走桌面原有流程。

默认 `oneShot:true`：每次启用只执行一次。设置 `oneShot:false` 后，前一任务结束，再等待 `intervalSeconds` 执行下一次，任务依次进行。`externalKey` 留空时每个任务生成新键，从而创建新会话。要演示重启恢复，设置固定的 `externalKey`，保留宿主数据，停止并重新启用插件：它会重新取得同一原生会话，随后提交一个新回合。临时 `handle` 不能跨重启保存。

`sessions.submit` 返回 `runId` 和 `started` / `queued`，表示任务已接收；`sessions.wait` 返回 `completed`、`failed` 或 `cancelled` 以及 `assistantMessages`，这是该回合的结果。示例订阅事件但只保存最终结果，最终输出以 `wait` 为准。

服务按 FIFO 顺序处理排队任务，每个任务通过已有的定向提示入口启动独立回合。空闲原生会话被运行时回收后，宿主会透明恢复它，插件继续使用已取得的 handle。

受管理的 Pi 会拒绝会话 new、fork、import、switch 等身份切换操作，以保持 `externalKey` 的绑定。需要另一个会话时，使用新的 `externalKey`。

停用时，SDK 唤醒本地等待，后台线程退出；宿主取消活动和排队任务，清理订阅及审批注册。如果活动原生回合正在等待审批，宿主保留该回合，把审批交回桌面原有流程，保留超时拒绝机制，仅取消排队任务。普通任务结束时示例释放 handle，持久会话与外部键映射仍由宿主管理。启用插件会使用所选模型，按该 Provider 的正常计费规则执行。

在导出的 SDK 环境中验证并打包：

```text
python -m umeko_plugin_sdk validate session-task-service
python -m umeko_plugin_sdk pack session-task-service session-task-service.zip
```
