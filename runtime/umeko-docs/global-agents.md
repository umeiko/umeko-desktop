# 全局子智能体与会话桥

用户在应用级 Widget「全局子智能体」创建持久协调者、指定模型与角色，并逐个开启普通会话的桥。协调者只有桥 API，实际工作由目标会话按自己的权限执行。普通模型不能开启桥、创建协调者或替用户批准操作。

`umeko_desktop` 协议：

- `agent_bus.overview`，`arguments:{}`：返回工作区与会话/全局子智能体的 `id,title,workspace,busy,bridge,kind` 及已加载会话的子代理状态元数据。只返回元数据，不读取其他会话正文。子代理通过其所属会话协调。
- `agent_bus.dispatch`，`arguments:{"targetId":"session:ID 或 agent:ID","text":"任务"}`：仅全局协调者可调用，目标必须由用户启用桥；返回 `status:accepted,requestId`。普通目标原有的工具权限、用户确认仍然适用。不要从 accepted 或 delivered 推断完成。
- `agent_bus.requests`，`arguments:{}`：只返回当前真实会话发出或收到的最近 64 个请求。状态为 queued/running/completed/failed/cancelled/interrupted。
- `agent_bus.reply`，`arguments:{"requestId":"请求 ID","status":"progress 或 completed 或 failed 或 cancelled","result":"进度或结果"}`：只能由真实收件会话回复；终态不可重复修改，进度间隔至少 5 秒。最终结果自动投递回来源协调者并唤醒它，进度只加入上下文。必须主动报告结果，普通 assistant 回复不会冒充完成回执。

每个请求最多 8000 字，30 分钟超时；全局最多 32 个未完成请求、每个目标 4 个。不要轮询忙等或反复委派同一操作。重启会把未完成任务标为 interrupted，用户可检查目标上下文再决定重试。模型不可以指定 source 身份，不能回复其他目标收到的请求。

协调者收到结果后继续综合和回复用户，不要仅为了确认收件而互相发送新任务，避免循环调用。
