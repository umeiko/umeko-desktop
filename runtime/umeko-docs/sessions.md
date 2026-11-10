# 项目与聊天会话

`projects.list` 查询项目 ID；`sessions.list` 查询会话元数据，可传 `offset`、`limit`（1–200）和 `workspace` 过滤。列表只返回元数据，不含聊天正文。`sessions.get` 按 `id` 读单项，省略 id 读取发起工具调用的会话。

项目操作：

- `projects.add`：`paths` 为目录路径数组，添加并打开项目。
- `projects.open`：按 `id` 切换项目。
- `projects.rename`：`id`、`title`。
- `projects.archive`：`id`、`archived`（默认 true），false 恢复。
- `projects.remove`：按 `id` 从项目列表移除，磁盘上的工作目录保留。
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

`sessions.open` 按 `id` 打开；`sessions.new` 创建当前项目的新草稿，首次发送后才生成持久化会话 ID。分支使用原生 Pi 历史树，标题前缀为 `(Fork1)` 等，操作后台进行；查询列表确认新 ID。归档会保留聊天；`sessions.delete` 会移除该会话及其 Umeko 管理的原始聊天文件。删除前按 ID 核对目标，确认是用户明确要删除的会话，必要时先导出备份。

正在使用的会话的删除、重命名、分支等操作可能排队，本轮结束后执行。工具报告 accepted/queued 时，告诉用户操作已排队，结束后再确认结果。工具调用始终归属发起它的会话，与用户当前查看的聊天无关。全量正文在返回的 `file` 路径，需要时分段读取超长 JSONL。
