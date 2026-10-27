# config_umeko 工具协议

参数形状：`{"operation":"操作名称","arguments":{...}}`。参数必须是 JSON 数据。它通过现有的桌面进程调用 Umeko 控制器，保存配置并发出相应刷新信号，不是 Shell，也不动态执行任意 Python/JavaScript。

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

`operations.list` 按需提供实际可用的写操作、参数类型和默认值；不必把所有文档一次读入上下文。会话列表每次最多 200 条，只返回元数据，不加载完整聊天。已有密码、令牌和认证头不会通过配置查询读出。

返回的 `ok:false` 表示失败，查看 `error`，不要宣称成功。同步完成的操作返回 `status:"applied"`；后台开始的工作返回 `accepted`，用 `status.get`、列表或目标状态核实。修改使用中的供应商、模型、会话或内核时返回 `queued` 和 `jobId`，本轮回复结束、相关任务空闲后自动执行。使用 `jobs.get` 的 `id` 查询实际结果。排队记录有数量和保留上限，等待空闲超过十分钟会失败；应用退出会丢弃未执行的队列。不要在同一轮中循环等待自身结束。

文件参数 `path` 使用本机绝对文件路径；工具负责转换本机 URL。项目 `paths` 是本机目录路径数组。配置和模型数组直接传 JSON，不需要把它们序列化成字符串。所有写操作都会使用桌面端已有的验证规则；错误信息不会回显输入中的密钥。

多个独立操作可以合并，最多 32 个：

```json
{"operation":"batch","arguments":{"operations":[
  {"operation":"appearance.language","arguments":{"language":"zh"}},
  {"operation":"appearance.fontScale","arguments":{"scale":1.25}}
]}}
```

批量按顺序提交，每项有各自结果，**不是事务**，失败不回滚已经应用的项。不要在一批中假设上一项排队操作已经完成。不支持嵌套批量。工具取消或超时不能证明桌面变更没有发生，重试前查询当前状态。

每个工具调用自动关联发起它的 Agent 会话。`models.select`、`sessions.reasoning` 可显式指定 `sessionId`，缺省作用于调用会话，即使用户此时正在查看别的聊天。全局外观与配置会立即更新界面；涉及内核重载的设置在相关任务结束后生效。
