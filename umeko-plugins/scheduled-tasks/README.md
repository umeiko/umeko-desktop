# 定时任务 / Scheduled Tasks

从右下角的小钟表 Widget 入口启用「定时任务」。新建一条预写消息，选择触发对象和时间。每个会话最多保留 **5 个定时器，停用项也计入**；删除后释放名额。关闭面板不停止计划，退出 Umeko 后停止调度。

Enable Scheduled Tasks from the clock Widget entry. Write a message, choose its destination and schedule. Each conversation can retain **5 timers, including disabled timers**. Deleting a timer frees a slot. Closing the panel keeps timers active; exiting Umeko stops scheduling.

## 两种触发方式 / Two schedule types

- **单次定时 / One time**：指定日期、时间和时区，只触发一次。时区使用 `Asia/Shanghai`、`UTC` 等 IANA 名称。
- **周期触发 / Repeat**：输入数值，单位只有**天、小时、分钟**，均支持小数。实际间隔不能小于 **15 秒**。例如 `0.25 分钟 = 15 秒`、`0.5 小时 = 30 分钟`、`1.5 天 = 36 小时`。

周期首次触发在启用后的一个完整间隔之后。重新启用从当时重新计时；编辑保存也重新开始计时。周期按经过的真实时间计算，不随夏令时改变。单次时间落在夏令时缺口时按偏移差向后移动，重复小时只取较早一次。

Intervals start one full period after enabling; enabling again or saving an edit restarts that period. Intervals use elapsed time, independent of daylight saving. A one-time local time in a DST gap moves forward by the offset change; a repeated local hour uses the earlier occurrence.

调度器每秒检查。错过的触发不会集中补发，长时间离线最多保留一小段错过记录，随后跳到下一个未来周期。运行记录中的「已投递」表示目标已收到消息，**不代表 Agent 已完成工作**；结果应在目标会话或 Agent Bus 中查看。投递失败不盲目重发，可检查原因后手动触发。

The scheduler checks once per second. Missed occurrences are not replayed in a burst; long downtime records a bounded missed backlog and resumes with a future occurrence. **Delivered means message receipt, not completed Agent work.** Review the target conversation or Agent Bus for results. Failed deliveries are not blindly resent.

## 触发对象 / Destinations

- **本会话主 Agent / This conversation’s main Agent**：沿用原聊天的模型、上下文和权限，走现有 Widget 消息通道，不发送输入框中的草稿或附件，也不切换前台聊天。
- **已关联全局智能体 / Connected global Agent**：只列出已通过 Agent Bus 与当前会话建立连接的全局智能体，通过现有 `agent_bus.dispatch` 投递。触发时再次检查关联；解除关联、删除对象或停用服务后会记录真实错误，不自动重建连接。

不用另建会话配置或填写供应商密钥。当前主聊天的定时消息支持 Pi 后端。停用、删除定时器仅阻止后续触发，已经投递的消息不会撤回，既有记录仍保留。删除会话或改变它的工作目录会让原计划的投递失败，避免发到另一个项目。

No separate session profile or provider key is required. Main-chat timer delivery currently supports Pi. Disabling/deleting a timer stops future triggers; submitted messages cannot be retracted and existing history is retained. Removing the original conversation or changing its workspace makes delivery fail rather than redirecting work.

## Agent 自主管理 / Agent API

使用现有 `umeko_desktop` 工具，不添加第二条工具或直接编辑数据库。先用 `widgets.list` 和 `widgets.docs` 读取入口，再通过 `widgets.call` 调用。返回 `accepted` 后，用 `widgets.result` 查询真实结果。

Use the existing `umeko_desktop` Widget API. Discover it through `widgets.list` / `widgets.docs`, call `widgets.call`, then inspect `widgets.result` after an accepted request. Do not edit the database directly.

```json
{"operation":"widgets.docs","arguments":{"id":"scheduled-tasks"}}
```

公开方法：

| 方法 | 作用 |
| --- | --- |
| `targets` | 列出本会话允许的触发对象：`main` 或已关联的 `agent:<id>` |
| `list` | 本会话的全部定时器，含停用项 |
| `create` | 新建，默认启用；每会话最多 5 个 |
| `enable` / `disable` | 用 `task_id` 启用或停用 |
| `delete` | 用 `task_id` 删除，释放名额 |
| `history` | 用 `task_id` 查看最近 20 次触发记录 |

新建每隔 2.5 小时发给本会话主 Agent 的定时器：

```json
{
  "operation": "widgets.call",
  "arguments": {
    "id": "scheduled-tasks",
    "method": "create",
    "arguments": {
      "name": "进度检查",
      "message": "检查当前项目的进度并简要汇报。",
      "target": "main",
      "enabled": true,
      "schedule": {"frequency":"interval", "interval_value":2.5, "interval_unit":"hours"}
    }
  }
}
```

周期单位为 `days`、`hours`、`minutes`。单次使用 `{"frequency":"once","first_date":"2026-12-01","local_time":"09:30:00","zone":"Asia/Shanghai"}`。全局对象的 `target` 必须从 `targets` 返回值中选择。

所有操作都绑定**真实调用会话**，不接受自填 owner/session ID；切换前台不会改变归属，也不能列出或删除其他会话的定时器。草稿得到正式会话 ID 后保留原定时器和 5 个名额限制。没有持久会话 ID 的草稿在应用重启后不可恢复投递。

Operations use the real calling conversation, not a model-supplied owner/session ID. Foreground changes do not change ownership. Other conversations cannot list or delete its timers. Draft promotion retains the same timers and quota. An unsaved draft without a persistent native session ID cannot receive timers after an application restart.
