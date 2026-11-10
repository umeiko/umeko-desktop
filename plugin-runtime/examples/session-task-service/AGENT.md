# 会话任务服务接口

此应用服务按配置在独立会话中运行任务。任务与当前聊天互不影响，结果保存在服务自己的状态中，权限以宿主批准的配置为上限。

`status {}` 立即返回内存中的最近任务状态。首次执行前为 `idle`；提交后为 `started` 或 `queued`，附带 `externalKey`、`sessionId`、`runId`；终态为 `completed`、`failed` 或 `cancelled`，附带 `assistantMessages`，失败时可有 `error`。获取会话或提交失败时只有 `status:failed` 与 `error`，没有模型输出。最近一次结果也写入插件状态目录的 `latest-task.json`；应用重启后、第一次任务开始前，内存状态为 `idle`。

使用 `widgets.call`，参数为 `{"id":"session-task-service","method":"status","arguments":{}}`，再通过 `widgets.result` 读取结果。`status` 只查询，不启动新任务。定时执行、任务文本、配置名和单次执行开关由插件配置控制。工作目录、桌面模型别名、工具与权限由用户批准：先停止应用，在当前或隔离应用 profile 的 `settings.json` 顶层配置 `pluginSessionProfiles`。服务排除 `umeko_desktop`、`pi`、`pi_commands` 这些桌面管理工具；子 Agent 继承同一配置上限，只使用该配置的模型。
