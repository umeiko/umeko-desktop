# Widget 插件：桌面面板与 Agent 交互

Widget 扩展 Umeko 的桌面界面和当前会话，例如文件管理器、版本管理。它使用 `umeko_plugin_sdk`，包清单为 `kind: "umeko-plugin"`、`apiVersion: 1`，与 [Provider 插件](provider-plugins.md) 使用不同的 SDK 和安装入口。

## 会话插件和应用常驻服务

- `lifecycle: "session"`（默认）：绑定聊天，可有页面或无页面，切换聊天时停止。
- `lifecycle: "application"`：无页面的应用级后台服务，跨聊天常驻。导入或升级后停用，使用插件管理的全局开关或 `widgets.enable` 明确启用后随应用启动。切换聊天、进入设置和关闭面板不停止；停用、升级、卸载或退出时停止。修改服务配置会重启该服务，异常停止后可重新启用重试。

`widgets.list` 返回 `lifecycle`、`active`、`running` 和 `starting`，应用级服务会出现在文档发现和管理列表，但不会出现在右侧页面选择器。应用级进程和 `context.state_dir` 属于整个应用，不能把当前前台聊天当作所有后台任务的目标。开发包的 `examples/application-service` 提供完整文件监听示例。

## 开发与使用

### 官方桌面小宠物

`desktop-pet` 是默认启用、默认隐藏的官方应用级 Widget。到“设置 → Agent → 插件管理 → 桌面小宠物”打开显示或导入形象；Agent 使用 `widgets.docs {"id":"desktop-pet"}` 获取管理和制作动画形象的完整文档，之后通过 `widgets.call` 调用 `show`、`hide`、`configure`、`importAppearance`、`selectAppearance` 等方法。形象支持透明 WebP / GIF / PNG 或 `umeko-pet` ZIP，独立于聊天角色配置。

后台观察每 1–2 秒读取活动摘要，所有动作至少保持 3 秒。它不调用模型、不扫描聊天历史、不向上下文推送活动通知。隐藏时卸载动画解码器，停用 Widget 时停止观察。该官方 Widget 使用宿主内置适配器；第三方 Widget 不能声明或取得同等宿主访问权限。

Widget 可以用 `settingsPage` 声明包内的 QML 设置页，根项同样声明 `required property var sdk`。设置页由插件管理加载，`sdk.call` 定向调用选中 Widget，`sdk.response` 接收结果，`sdk.colors` / `scale` / `t(text)` 提供样式和翻译，`sdk.active` 表明服务是否可用。没有设置页的 Widget 继续使用原来的 JSON 配置编辑器。应用服务的 `settingsPage` 不会创建聊天侧栏页面。

从“设置 → Agent → 插件管理 → 导出 SDK 和示例”取得当前版本的 SDK、协议和完整示例。先阅读导出包的 `README.md`，以其中接口为准。典型结构：

```text
my-widget/
  manifest.json
  README.md
  config.json
  config.schema.json
  scripts/plugin.py
  qml/Main.qml
```

Python 类继承 `umeko_plugin_sdk.Plugin`，在 `handle(method, arguments)` 中处理页面请求；QML 根项声明 `required property var sdk`。在包含 SDK 的 Python 环境运行：

```text
python -m umeko_plugin_sdk validate my-widget
python -m umeko_plugin_sdk pack my-widget my-widget.zip
```

在“设置 → Agent → 插件管理”导入 ZIP，启用当前会话，再从聊天右下角的插件按钮打开。开发目录中的内置示例可直接参考 `umeko-plugins/file-tree` 和 `umeko-plugins/git-viewer`；安装版应使用导出包中的示例，不要假定安装目录可写。

所有 Widget 管理和通信复用 `umeko_desktop` 的 `widgets.*` 操作；`plugins.import`、`plugins.login`、`plugins.resource` 等仍只属于 Provider 插件。每个 Widget ZIP 必须包含 20 字以内的单行 `summary`、`agent.document` 指向的完整非空 Markdown，以及 `agent.methods` 公开方法清单；文档最多 64 KiB。缺少这些材料会在安装时拒绝。

## Agent 如何发现、管理和调用 Widget

先调用 `help`，参数 `{"topic":"widget"}`，获取本指南和已激活的 Widget；或调用 `widgets.list`，参数 `{"activeOnly":true}`。列表包含简介、激活/打开状态、文档路径和公开方法名。再调用 `widgets.docs`，参数 `{"id":"目标 ID"}`，获取完整文档与参数 schema。

| 操作 | 参数与含义 |
| --- | --- |
| `widgets.import` | `path`：导入本机 ZIP，后台验证和安装 |
| `widgets.enable` | `id`、`enabled`：全局启用或停用 |
| `widgets.activate` | `id`、`enabled`：在当前聊天激活或停用 |
| `widgets.open` / `widgets.close` | 前者传 `id` 打开页面；后者关闭当前 Widget 页面 |
| `widgets.config` | `id`、完整 `config` 对象，后台校验保存 |
| `widgets.uninstall` | `id`，卸载用户安装的包 |
| `widgets.resource` / `widgets.exportSdk` | 获取 Widget SDK 路径；或传 `path` 导出 |
| `widgets.call` | `id`、`method`、`arguments` 对象；仅调用插件声明的公开方法 |
| `widgets.result` | `requestId`，取实际结果及请求期间的更新消息 |
| `widgets.messages` | 可选 `id`、`after` 游标、`limit`（1–100），读取当前聊天的消息记录 |

```json
{"operation":"widgets.call","arguments":{"id":"git-viewer","method":"status","arguments":{}}}
```

调用立即返回 `accepted`、`requestId`、`jobId`。用 `widgets.result` 的 `requestId` 查询到 `completed` 或 `failed`，其中 `result` 包含 `{ok,result}` 或 `{ok:false,error}`，`updates` 包含该 Widget 在此请求期间推送的消息。也可用 `jobs.get` 观察最终状态。默认调用超时 20 秒，可通过 `timeoutMs` 调整为 1–120 秒；超时会停止该插件进程。当前最多保留 64 项请求，退出后不恢复未完成调用。

会话级 Widget 调用绑定当前显示的主会话。应用级服务可接受已经在后台运行的其他聊天发起的调用，每次调用的参数、工作区、结果和更新都绑定发起它的聊天，其他聊天不能查询其请求结果。已激活的 Widget 可通过调用按需启动；展示界面的公开方法应先打开页面，应用服务不调用 `widgets.open`。

## Widget 如何向 Agent 提供信息

调用链是：页面 → 插件 Python → Umeko 宿主 → 当前聊天 → Pi Agent。

| 目的 | Python SDK | 实际效果 |
| --- | --- | --- |
| 让 Agent 处理一段文字 | `context.send_message(text)` | 通过聊天的普通发送流程提交；正在回复时进入后续消息队列 |
| 影响正在运行的任务 | `context.send_message(text, steering=True)` | 通过聊天的引导流程提交，沿用 Umeko 当前的打断和继续行为 |
| 提供工作区文件 | `context.attach_file(relative)` | 放入当前聊天输入框的附件列表，等待用户或后续发送动作一起发送 |
| 仅提示用户 | `context.notify(message)` | 显示简短界面通知，不加入 Agent 上下文 |
| 实时推送进度和数据 | `context.notify_agent(message, data={}, request_id=None, wake=True)` | 主动注入主 Agent 上下文，同时保留可查询的消息记录 |

`send_message` 要求 `session.write`；`attach_file` 还要求 `workspace.read`。它们沿用前台聊天输入框操作。会话插件切换后的旧进程事件会被丢弃；应用服务的跨聊天通知使用下面的 `notify_agent` 和显式目标。

例如，页面上的“请 Agent 检查”按钮调用 `sdk.call("ask_agent", {path: "src/main.py"})`，对应实现可为：

```python
from umeko_plugin_sdk import Plugin

class MyWidget(Plugin):
    def handle(self, method, arguments):
        if method == "ask_agent":
            self.context.attach_file(arguments["path"])
            self.context.send_message("请检查附加文件，并说明发现的问题。")
            return {"submitted": True}
        return {"workspace": str(self.context.workspace)}

def create_plugin(context):
    return MyWidget(context)
```

`submitted` 是插件自己返回给页面的数据，不能当成 Agent 已完成任务的凭据。`send_message` 和 `attach_file` 保留聊天输入框原有行为，会沿用已有附件。新的实时通信使用 `notify_agent`，独立于输入框草稿和附件。

## 实时消息的送达与查询

1. 插件调用 `context.notify_agent("正在检查", data={"step":1})`，SDK 返回唯一消息 ID，并自动附上当前 `context.request_id`。异步线程应先保存请求 ID，再通过 `request_id=` 显式传入。
2. Umeko 验证插件权限、激活状态和会话归属，先保存消息记录，再通过已有 Pi 进程通道推送具名的 `umeko-widget-update` 自定义消息。
3. Agent 正在运行时使用 Pi 原生 `steer`，在下一个安全处理节点送达；不会重启正在执行的命令或改写已经发出的模型请求。空闲时默认触发新回合。`wake=False` 只注入上下文，不主动触发新回合。
4. 消息进入 Agent 上下文后回传 `delivered`；此前可为 `pending`、`sending`、`queued`，失败为 `failed`。Python 的 `Plugin.on_event("agent.delivery", data)` 可收到回执。进入上下文不代表 Agent 已理解或完成业务处理。
5. 主 Agent 无需轮询就会收到推送；之后可用 `widgets.messages` 按 `nextCursor` 增量查询，也可用 `widgets.result.updates` 一并读取请求结果和运行期间的通知。

应用级后台任务应在开始时保存 `target = context.capture_session()`，完成后使用 `context.notify_agent(..., session=target)`。调用中的 `context.request_session`、`request_id` 和 `call_source` 为线程隔离的请求上下文；额外线程不会继承其他请求。没有指定目标且无法通过原请求 ID 关联的应用级通知会被拒绝。用户此时切到另一聊天不会改变目标；原聊天已加载时可唤醒其后台 Agent，未加载时保留等待再次加载。工作区改变后的旧目标会收到失败回执，不能把结果改投给新聊天。

每条通知文本最多 8000 字，总事件最多 32 KiB；每个 Widget 每分钟最多 60 条。每个目标聊天保留最近 100 条、最多 1 MiB 的消息记录，`historyTruncated` 标明更早记录被淘汰。应用级服务尚未投递且目标暂未加载的消息可等待它再次加载；应用退出或进程中断后，已尝试但未确认的消息标为 `interrupted`，不会自动重放。任务结果来自方法返回或插件文档中明确约定的结构化协议。

## Widget 如何读取 Umeko 的信息

| 接口 | 数据与更新方式 |
| --- | --- |
| `sdk.session` / `context.session` | 当前会话 `id`、实例 `token`、标题、工作区、忙碌状态；宿主随会话变化同步 |
| `session.read` 权限 | 额外提供最近 8 条消息的角色和文本，每条最多 2000 字符 |
| `sdk.config` / `context.config` | 按插件 schema 验证后的配置 |
| `sdk.colors`、`sdk.scale`、`sdk.active` | 页面主题、字号缩放和当前是否可交互 |
| `context.resolve_workspace(relative)` | 在授权工作区内解析文件路径，要求 `workspace.read` |
| `context.state_dir` | 按插件和会话划分的持久状态目录 |

页面调用 `sdk.call(method, arguments)` 会立即得到请求 ID，Python 处理后的结果通过 `sdk.response(id, {ok, result, error})` 异步返回。耗时读取应放在 Python，页面只做交互和展示。

Umeko 会合并聊天更新，约每 200ms 同步一次最新会话快照；它不是每个 token 的独立事件。QML 可用 `Connections` 监听 `sdk.sessionChanged`；Python 覆盖 `Plugin.on_event("session.changed", snapshot)` 接收快照。长时间执行的 `handle()` 会延迟该进程处理后续快照，耗时任务应可取消地在后台执行。

Agent 可调用插件公开方法传入结构化数据。插件通过 `context.publish(topic, data)` 更新当前可见页面，QML 监听 `sdk.event(topic, data)`；页面未打开时不缓存界面事件，应在重新打开时从插件状态读取。事件负载最多 64 KiB。

## 当前能力边界

- Agent 收到的是正常聊天消息与已发送附件，不会直接收到 QML 事件，也不会自动理解 Widget 的内部状态。
- Widget 可以通过有权限的会话快照观察 Agent 的最新文本，但这是有界摘要，不是完整历史、逐条事件流或可靠的任务结果回调。
- Agent 通过统一桌面工具调用 Widget 公开方法和传入结构化数据；插件不会另行注册为 Pi 扩展或 MCP。
- 快照和 SDK 不提供供应商密钥、登录凭据或完整系统提示词。前台快照只包含当前聊天；应用服务的每次调用还可取得发起调用聊天的授权快照。应用服务跨聊天运行，方法结果和通知仍按目标聊天隔离。
- Widget 的 Python、QML 和所附程序属于用户选择执行的本机代码；独立进程和 SDK 权限检查不等同于操作系统沙箱。

通信使用宿主生成的请求 ID、插件声明的参数 schema 和当前会话绑定。完整接口说明应放在包内的 Agent 文档中，供模型按需读取。
