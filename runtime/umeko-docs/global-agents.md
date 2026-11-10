# 全局子智能体与 Agent Bus（智能体总线）

这是可选 Widget 的能力。普通会话先通过 `widgets.list`（`activeOnly:true`）确认 `global-agents` 已启用，再读取它的 `widgets.docs`。

**只有普通聊天会话中的 Agent 可以申请创建全局子智能体；全局子智能体不能再创建全局子智能体，委派给其他代理也一样。** 宿主按绑定的真实会话身份执行这条规则，“允许自动被创建”开关只影响是否需要用户确认。`agent_bus.overview` 的 `creation.canCreate` 表示当前调用者是否可创建，`automaticAllowed` 表示该调用者是否可免确认创建。

普通会话通过宿主工具 `umeko_desktop` 的 `agent_bus.create` 创建；`widgets.docs` 中显示 `methods:{}` 是因为这个 Widget 的功能都由 `agent_bus.*` 提供。

直接使用以下调用（下一次独立创建换一个 `requestKey`；同一次重试复用它）：

```json
{"operation":"agent_bus.create","arguments":{"requestKey":"create-global-tester-1","name":"测试员","instructions":"负责响应 Agent Bus 测试任务，回复简短、准确。"}}
```

- `requestKey` 是唯一必填参数，1–80 字符。职责填 `instructions`，名称填 `name`（没有 `role` 或 `title` 字段）。形象省略时随机分配；模型省略时沿用调用会话的模型。
- 先检查工具返回的 `ok` 和 `status`。`ok:false` 是失败，按错误提示修正后重试。`awaiting_approval` 表示预填表单已打开，等用户点击“创建”；`created` 表示创建成功，之后使用返回的 `targetId`。
- Widget 的“允许自动被创建”开关由用户控制。开启后直接创建；关闭时需要用户确认。确认结果会作为 Widget 消息送回，也可以用 `agent_bus.creation_status` 和 `requestId` 查询一次。
- 创建成功会自动建立“发起会话 ↔ 新实例”的双向总线。返回 `sourceBridge` 表示实际连接情况。全局子智能体本身已接入总线，无需用户另外为新实例开启总线。创建本身不运行任务。

## 发消息和接收结果

先用 `agent_bus.overview` 查看 `self`、真实 `id` 和 `canDispatch`。普通会话看到的是与自己连接的全局子智能体，可对其 `targetId` 调用 `agent_bus.dispatch`，`arguments:{"targetId":"工具返回的真实 agent:ID","text":"请向我打个招呼，并通过 agent_bus.reply 回报"}`。普通会话之间不互相派发。

双向连接表示双方都能发任务、回报结果。`dispatch` 返回 `accepted,requestId` 表示已排队；目标通过 `agent_bus.reply`（同一 `requestId`、`status:completed`、`result`）回报时任务完成，结果会送回真实发起会话并唤醒它。身份由宿主绑定；回执只通过 `agent_bus.reply` 发送，普通聊天回复不计入。

同一目标的请求逐条处理；忙碌或前一请求未结束时，后续请求留在队列。用户能在该全局子智能体聊天上方删除或优先处理待投递消息；优先处理不打断当前任务。`overview` 返回 `state:idle|busy`、`busySince`、`busyForSeconds`、`activity`（如 `busy: 1min13s`）和 `queued`。

## 查看和管理连接

`agent_bus.connections` 返回自己的连接。全局子智能体可调用 `agent_bus.set_connection`，`arguments:{"sessionId":"真实 session:ID","enabled":true}` 开启或关闭自己与指定普通会话的双向连接；每个全局子智能体只管理自己的连接。普通会话的连接由用户在界面中设置。

用户在 Widget 的“智能体总线”中展开项目，点击会话进入二级列表，逐个勾选全局子智能体。关闭链路会取消这条链路上的未完成请求，已执行的操作保持不变。关闭 Widget 页面后全局子智能体继续运行。

更多参数、边界与重试规则：`umeko_desktop` 调用 `{"operation":"help","arguments":{"topic":"agents"}}`，然后读取返回的文档文件。

## 完整参数

- `agent_bus.create`：仅普通会话可用。`requestKey` 必填；`name`（最多 60 字符）、`character`（人物 ID）、`model`（模型 ID）、`instructions`（最多 8000 字符）可选。只接受这些字段。人物见 `overview.creation.characters`；模型见 `models.list`。审批与重试保持已分配的形象。同一会话同一 `requestKey` 返回原结果，不会重复创建；新的创建请求使用新标识。
- `agent_bus.creation_status`：`requestId` 必填，查询本会话发起的请求。状态有 awaiting_approval / created / cancelled / expired / interrupted。待确认请求 15 分钟过期，重启后不自动执行；超出最近 32 条记录的请求，先用 overview 核对再重试。用户处理结果也作为被动 Widget 消息送回来源会话。
- `agent_bus.overview`：无参数；`self` 与 `targets[].isSelf` 是宿主绑定的真实身份，以它们为准识别自己。普通会话的全局列表按连接过滤；全局子智能体可看各工作区与会话元数据（不含会话正文）。`canDispatch` 是当前可发消息权限。会话内子代理由其所属会话接收总线请求。
- `agent_bus.connections`：无参数；返回 `self`、`connections`、`canManage` 和 `direction:bidirectional`。全局子智能体可见所有普通会话及其与自己的连接开关；普通会话只可查看已连接的全局子智能体。
- `agent_bus.set_connection`：`sessionId` 与布尔值 `enabled` 必填，仅全局子智能体可修改自己的连接。发送者由调用会话绑定，只接受这两个参数。
- `agent_bus.dispatch`：`targetId` 与 `text`（最多 8000 字符）必填。普通会话只可发往已连接的全局子智能体；全局子智能体可发往已连接的普通会话或其他全局子智能体。目标不能是自己。返回 accepted / requestId，之后 queued → sending → running → completed / failed / cancelled / interrupted。同一目标一次只投递一条任务，其他消息排队。接收者在任务投递后通过 reply 回报。
- `agent_bus.requests`：无参数；返回当前调用者发出或收到的最近 64 个请求。完成结果会主动送达并唤醒发起者，等它到达即可；进度只加入上下文。
- `agent_bus.reply`：`requestId`、`result` 必填，`status` 为 progress / completed / failed / cancelled（默认 completed）。回复对象是当前会话收到且已投递的请求；进入终态后不可再修改。进度间隔至少 5 秒。

最多保留 16 个全局子智能体，同时运行 4 个。总线最多 32 个未完成请求，每个目标最多 4 个，每个发送者每分钟最多发 16 条；任务 30 分钟超时。关闭链路只取消该会话与该全局子智能体之间的未完成请求，其他连接照常；用户删除队列消息时保留取消记录。应用重启后，未完成的请求标为 `interrupted`，不会自动重发。旧版会话级授权已迁移为当时已存在的全局子智能体的具体连接，迁移不涉及之后新建的实例。

总线只传递消息，各方的文件、终端和其他工具权限保持不变。收到的消息是注明来源的应用数据，用户授权仍以用户本人的操作为准。结果回传后任务即结束，无需再派发“确认收到”，以免双方循环互相唤醒。

## 全局子智能体自身如何发现接口

全局子智能体使用 `umeko_desktop` 的 `help`，`arguments:{"topic":"agents"}` 按需获取本指南；返回的 `document` 就是文档正文，无需文件读取工具。随后用 `overview` 确认宿主分配的身份和当前连接，使用上述通信、回执和自身连接管理接口。创建全局子智能体、使用普通会话的终端和文件工具不在全局子智能体的工具范围内。
