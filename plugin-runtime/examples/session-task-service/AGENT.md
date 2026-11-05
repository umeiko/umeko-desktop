# 会话任务服务接口

此应用服务按配置运行独立会话任务。它不把当前聊天当作任务目标，不向聊天通知结果，也不改变插件配置来扩大宿主批准的权限。

`status {}` 立即返回内存中的最近任务状态。首次执行前为 `idle`；提交后为 `started` 或 `queued`，附带 `externalKey`、`sessionId`、`runId`；真实终态为 `completed`、`failed` 或 `cancelled`，附带 `assistantMessages`，失败时可有 `error`。获取或提交失败时只有 `status:failed` 与 `error`，不能据此认为模型执行过。最近一次结果也写入插件状态目录的 `latest-task.json`，重启后第一次任务开始前的内存状态重新为 `idle`。

使用 `widgets.call`，参数为 `{"id":"session-task-service","method":"status","arguments":{}}`。调用结果应通过 `widgets.result` 读取。`status` 不启动新任务。定时执行、任务文本、配置名和单次执行开关由插件配置控制。用户需先停止应用，在当前或隔离应用 profile 的 `settings.json` 顶层配置 `pluginSessionProfiles`，批准工作目录、现有桌面模型别名、工具与权限；目前没有新增的图形化配置编辑器。服务不允许 `umeko_desktop`、`pi`、`pi_commands` 桌面管理工具；子 Agent 同样继承配置上限，并只能使用该配置的模型。
