# 版本管理 · Agent 使用文档

简介：查看 Git 状态、历史与差异。Widget ID：`git-viewer`。要求本机 Git 可用，并选择有效的工作区。

通过 `umeko_desktop widgets.list` 查询激活状态；`widgets.docs` 返回当前版本的方法参数。按用户意图用 `widgets.activate` 激活，用 `widgets.open` 打开页面。

## 公开方法

| 方法 | 参数 | 返回与效果 |
| --- | --- | --- |
| `status` | `{}` | 当前分支、仓库状态、更改文件及暂存分组 |
| `history` | `{"all":true}`，可省略 | 有界提交列表、引用和真实父提交拓扑 |
| `branches` | `{}` | 本地分支、已有远程引用、标签 |
| `diff` | `{"path":"src/main.py","group":"changes"}` | 文件的有界文本差异；group 可为 staged、changes、untracked |
| `showDiff` | 同 diff | 将差异发布到已打开的版本管理面板 |

文件路径相对于当前聊天工作区。先 `widgets.open` 再调用 `showDiff`，其 `published:true` 表示页面事件已发出。差异可能截断，检查 `truncated`；查询不执行网络同步。

```json
{"operation":"widgets.call","arguments":{"id":"git-viewer","method":"status","arguments":{}}}
```

调用立即返回 `accepted`、`requestId`、`jobId`；随后调用 `widgets.result`，参数 `{"requestId":"返回的 ID"}`，获取 `completed`/`failed`、实际 `result` 和本次调用期间的 `updates`。`jobs.get` 也提供最终工作状态。`widgets.messages` 使用 `id:"git-viewer"` 按游标读取通知。

Agent 接口公开的是查询和页面展示。暂存、提交、丢弃、切换分支等由用户在界面操作。切换聊天、停用或关闭对应页面会取消其运行中的请求。
