# 文件管理器 · Agent 使用文档

简介：浏览文件并附加到聊天。Widget ID：`file-tree`。

先用 `umeko_desktop` 的 `widgets.list` 查询激活状态。未激活时可按用户意图调用 `widgets.activate`，参数 `{"id":"file-tree","enabled":true}`。`widgets.open` 打开页面。

## 公开方法

- `list`：`{"path":".","showHidden":false}`，读取一层目录的文件元数据。参数均可省略，返回 `entries`、`truncated` 与工作区名称。目录逐层读取，有数量与深度上限。
- `focus`：`{"path":"src/main.py"}`，在已打开页面展开父目录并选中文件。先打开页面，再调用；`published:true` 表示页面事件已发出。

路径相对于当前聊天的工作目录，拒绝访问工作区外的文件。Agent 接口仅公开上述方法，文件修改由用户通过界面操作。

```json
{"operation":"widgets.call","arguments":{"id":"file-tree","method":"list","arguments":{"path":"."}}}
```

返回 `accepted`、`requestId`、`jobId`。使用 `widgets.result`，参数 `{"requestId":"返回的 ID"}`，查询至 `completed` 或 `failed`；`result.ok` 和 `result.result` 是实际结果。也可用 `jobs.get` 查看最终状态。

`widgets.messages` 的 `id` 为 `file-tree`，用于按游标读取本会话的 Widget 通知。此插件通常直接返回方法结果；`focus` 通过结构化页面事件更新可见选择。

文件单击只选中，双击才放入聊天输入框的附件列表。附件在后续发送后进入 Agent 上下文。切换聊天、停用或关闭对应页面会取消该页面正在执行的请求。
