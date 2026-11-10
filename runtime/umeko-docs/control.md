# umeko_desktop 工具协议

参数形状：`{"operation":"操作名称","arguments":{...}}`。参数必须是 JSON 数据。工具通过现有的桌面进程调用 Umeko 控制器，保存配置并发出相应刷新信号；它只执行列出的操作，运行命令请使用 shell 工具。

常用只读操作：

```json
{"operation":"settings.get"}
{"operation":"providers.list"}
{"operation":"plugins.list"}
{"operation":"themes.list"}
{"operation":"projects.list"}
{"operation":"sessions.list","arguments":{"offset":0,"limit":100}}
{"operation":"sessions.get","arguments":{"id":"会话ID"}}
{"operation":"mcp.get","arguments":{"scope":"global"}}
{"operation":"status.get"}
{"operation":"operations.list","arguments":{"prefix":"providers."}}
```

`operations.list` 按需提供实际可用的写操作、参数类型和默认值，需要时再查，无需一次读入所有文档。会话列表每次最多 200 条，只返回元数据。已保存的密码、令牌和认证头在配置查询中显示为脱敏值。

返回 `ok:false` 表示失败，按 `error` 处理并如实告诉用户。同步完成的操作返回 `status:"applied"`。后台工作返回 `status:"accepted"` 和 `jobId`，表示已经开始。修改使用中的供应商、模型、会话或内核时返回 `status:"queued"` 和 `jobId`，相关任务空闲后自动执行。

保存返回的 `jobId`，用下面的请求查询同一项工作的最终结果：

```json
{"operation":"jobs.get","arguments":{"id":"返回的 jobId"}}
```

响应中的 `jobs` 数组包含 `id`、`operation`、`status` 和完成后的 `result`。状态为 `queued`（等待空闲）、`running`（正在执行）、`done`（已完成）或 `failed`（失败）。排队、执行和完成始终使用同一个 ID。状态为 `done` 时报告完成；`failed` 时查看 `result.error`。内核检查结果包含实际返回的版本，Agent 刷新完成结果可包含实际加载的 `resources`。`status.get` 也提供当前内核的 busy/status/version 和最近一次发送被拒绝的原因。

普通 Agent 在当前模型回合中调用 `agent.refresh` 或内核操作时，这项操作要等当前回合结束才能执行。因此先告诉用户任务已排队并结束本轮，用户下一轮询问时再用同一 `jobId` 查询结果；查询进度只用 `jobs.get`，同一操作提交一次即可。排队记录有数量和保留上限，等待空闲超过十分钟会失败；任务记录保存在内存中，应用退出后清空。

文件参数 `path` 使用本机绝对文件路径；工具负责转换本机 URL。项目 `paths` 是本机目录路径数组。配置和模型数组直接传 JSON 对象和数组。所有写操作都使用桌面端已有的验证规则；错误信息中的密钥会被隐去。

多个独立操作可以合并，最多 32 个：

```json
{"operation":"batch","arguments":{"operations":[
  {"operation":"appearance.language","arguments":{"language":"zh"}},
  {"operation":"appearance.fontScale","arguments":{"scale":1.25}}
]}}
```

批量按顺序提交，每项有各自结果；某项失败时，已经应用的项保持生效。同一批里的排队操作在后台各自完成，依赖前一项结果的操作放到下一次调用。批量不能嵌套。工具取消或超时后，桌面变更可能已经生效，重试前先查询当前状态。

每个工具调用自动关联发起它的 Agent 会话。`models.select`、`sessions.reasoning` 可显式指定 `sessionId`，缺省作用于调用会话，即使用户此时正在查看别的聊天。全局外观与配置会立即更新界面；涉及内核重载的设置在相关任务结束后生效。
