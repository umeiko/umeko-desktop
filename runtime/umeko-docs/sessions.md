# 项目与聊天会话

`projects.list` 查询项目 ID；`sessions.list` 查询会话元数据，可传 `offset`、`limit`（1–200）和 `workspace` 过滤。列表不会把长聊天正文灌入模型上下文。`sessions.get` 按 `id` 读单项，省略 id 读取发起工具调用的会话。

项目操作：

- `projects.add`：`paths` 为目录路径数组，添加并打开项目。
- `projects.open`：按 `id` 切换项目。
- `projects.rename`：`id`、`title`。
- `projects.archive`：`id`、`archived`（默认 true），false 恢复。
- `projects.remove`：按 `id` 从项目列表移除，不删除磁盘工作目录。
- `projects.fold`：按 `id` 切换列表折叠。
- `workspace.set`：按 `path` 打开工作目录。
- `items.pin`：`kind` 为 `project` 或 `session`，`id` 为对应 ID，切换置顶。

会话操作：

```json
{"operation":"sessions.rename","arguments":{"id":"会话ID","title":"新标题"}}
{"operation":"sessions.fork","arguments":{"id":"会话ID"}}
{"operation":"sessions.archive","arguments":{"id":"会话ID","archived":true}}
{"operation":"sessions.export","arguments":{"id":"会话ID","path":"C:/work/chat-backup.jsonl"}}
```

`sessions.open` 按 `id` 打开；`sessions.new` 创建当前项目的新草稿，首次发送后才生成持久化会话 ID。分支使用原生 Pi 历史树，标题前缀为 `(Fork1)` 等，操作后台进行；查询列表确认新 ID。归档保留聊天，删除则不同：`sessions.delete` 会移除该会话及其 Umeko 管理的原始聊天文件。执行删除前核对 ID 和用户明确意图，不能因为标题相近就删除另一个聊天。可先导出备份。

正在使用的会话的删除、重命名、分支等操作可能排队；本轮结束后执行。工具报告 accepted/queued 时不要宣称操作已经完成。切换可见会话不会改变后台工具调用的来源。全量正文在返回的 `file` 路径，只有确有需要才分段读取，避免一次读入整个超长 JSONL。
