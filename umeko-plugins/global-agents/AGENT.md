# 全局子智能体与 Agent Bus（智能体总线）

这是可选 Widget 的能力，普通会话通过 `widgets.list`（`activeOnly:true`）发现启用状态后再使用。

**只有普通聊天会话中的 Agent 可以申请创建全局子智能体。全局子智能体不能再创建全局子智能体，也不要通过委派绕过限制。** 宿主按真实会话身份强制执行，开启“允许自动被创建”不会解除限制。`agent_bus.overview` 的 `creation.canCreate` 表示当前调用者是否可创建，`automaticAllowed` 表示是否可免确认创建。

普通会话调用宿主工具 `umeko_desktop` 的 `agent_bus.create`；`widgets.docs` 中的 `methods:{}` 仅表示没有 `widgets.call` 管理方法，不表示普通会话没有创建能力。

直接使用以下调用（下一次独立创建换一个 `requestKey`；同一次重试复用它）：

```json
{"operation":"agent_bus.create","arguments":{"requestKey":"create-global-tester-1","name":"测试员","instructions":"负责响应 Agent Bus 测试任务，回复简短、准确。"}}
```

- `requestKey` 是唯一必填参数，1–80 字符。职责填 `instructions`，名称填 `name`，不要猜 `role` 或 `title`。形象省略时随机分配；模型省略时沿用调用会话的模型。
- 先检查工具返回的 `ok` 和 `status`。`ok:false` 是失败，按错误提示修正，不能报告创建成功或编造 ID。`awaiting_approval` 只是预填表单已打开，等用户点击“创建”；`created` 才表示实际创建成功，使用返回的 `targetId`。
- Widget 的“允许自动被创建”开关由用户控制。开启后直接创建；关闭时需要确认。可用 `agent_bus.creation_status` 和 `requestId` 查询确认结果，不要忙等轮询。
- 创建成功会自动建立“发起会话 ↔ 新实例”的双向总线。返回 `sourceBridge` 表示实际连接情况。全局子智能体本身已接入总线，无需用户另外为新实例开启总线。创建本身不运行任务。

## 发消息和接收结果

先用 `agent_bus.overview` 查看 `self`、真实 `id` 和 `canDispatch`。普通会话只会看到与自己连接的全局子智能体，可对其 `targetId` 调用 `agent_bus.dispatch`，`arguments:{"targetId":"工具返回的真实 agent:ID","text":"请向我打个招呼，并通过 agent_bus.reply 回报"}`。普通会话不能向其他普通会话派发。

双向连接表示双方都能发任务、回报结果。`dispatch` 返回 `accepted,requestId` 是已排队；目标通过 `agent_bus.reply`（同一 `requestId`、`status:completed`、`result`）回报后才算完成。结果会送回真实发起会话并唤醒它。身份由宿主绑定，不能冒用别人的 ID 或把普通聊天回复当作总线回执。

同一目标的请求逐条处理；忙碌或前一请求未结束时，后续请求留在队列。用户能在该全局子智能体聊天上方删除或优先处理待投递消息；优先处理不打断当前任务。`overview` 返回 `state:idle|busy`、`busySince`、`busyForSeconds`、`activity`（如 `busy: 1min13s`）和 `queued`。

## 查看和管理连接

`agent_bus.connections` 返回自己的连接。全局子智能体可调用 `agent_bus.set_connection`，`arguments:{"sessionId":"真实 session:ID","enabled":true}` 开启或关闭自己与指定普通会话的双向连接；不能替另一个全局子智能体改连接。普通会话不能改授权。

用户在 Widget 的“智能体总线”中展开项目，点击会话进入二级列表，逐个勾选全局子智能体。关闭链路会取消这条链路上的未完成请求，不撤销已执行的操作。关闭 Widget 页面不会停止全局子智能体。

更多参数、边界与重试规则：`umeko_desktop` 调用 `{"operation":"help","arguments":{"topic":"agents"}}`，读取返回的 `document` 正文或文档文件。全局子智能体自身也通过该入口按需获取指南，无需文件读取工具。
