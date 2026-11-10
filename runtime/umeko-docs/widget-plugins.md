# Widget 插件：桌面面板与 Agent 交互

Widget 扩展 Umeko 的桌面界面和当前会话，例如文件管理器、版本管理。它使用 `umeko_plugin_sdk`，包清单为 `kind: "umeko-plugin"`、`apiVersion: 1`，与 [Provider 插件](provider-plugins.md) 使用不同的 SDK 和安装入口。

## 会话插件和应用常驻服务

- `lifecycle: "session"`（默认）：绑定聊天，可有页面或无页面，切换聊天时停止。
- `lifecycle: "application"`：应用级常驻插件，可提供页面（如终端）或作为无页面的后台服务。导入或升级后停用，使用插件管理的全局开关或 `widgets.enable` 明确启用后随应用启动。切换聊天、进入设置和关闭面板不停止；停用、升级、卸载或退出时停止。修改配置会重启该插件，异常停止后可重新启用重试。

`widgets.list` 返回 `lifecycle`、`active`、`running` 和 `starting`，有页面的插件出现在右侧页面选择器，无页面的服务仅出现在文档发现和管理列表。应用级进程和 `context.state_dir` 属于整个应用；后台任务的目标聊天按下文“实时消息的送达与查询”中的方式在任务开始时捕获。开发包的 `examples/application-service` 提供完整文件监听示例，`examples/terminal` 提供共享终端示例。

## 开发与使用

### 官方桌面小宠物

`desktop-pet` 是默认启用、默认隐藏的官方应用级 Widget。到“设置 → Agent → 插件管理 → 桌面小宠物”打开显示或导入形象；Agent 使用 `widgets.docs {"id":"desktop-pet"}` 获取管理和制作动画形象的完整文档，之后通过 `widgets.call` 调用 `show`、`hide`、`configure`、`importAppearance`、`selectAppearance` 等方法。形象支持透明 WebP / GIF / PNG 或 `umeko-pet` ZIP，独立于聊天角色配置。

后台观察每 1–2 秒读取活动摘要，所有动作至少保持 3 秒。它只读取活动摘要，不调用模型、不扫描聊天历史、不向上下文推送通知。隐藏时卸载动画解码器，停用 Widget 时停止观察。该官方 Widget 使用宿主内置适配器，这项访问权限仅供它使用。

Widget 可以用 `settingsPage` 声明包内的 QML 设置页，根项同样声明 `required property var sdk`。设置页由插件管理加载，`sdk.call` 定向调用选中 Widget，`sdk.response` 接收结果，`sdk.colors` / `scale` / `t(text)` 提供样式和翻译，`sdk.active` 表明服务是否可用。没有设置页的 Widget 使用 JSON 配置编辑器。应用服务的 `settingsPage` 只出现在插件管理中。

设置页可用 `sdk.saveConfig(object)` 保存完整配置，返回请求 ID，通过 `sdk.configSaved(id,value)` 接收成功或失败；保存成功后 `sdk.config` 更新。清单可选 `liveConfig:true`：宿主先校验并保存配置，再更新运行中 worker 的 `context.config`，发送 `Plugin.on_event("config.changed",config)`，进程和临时状态保持不变。未声明时保存配置会重启服务。耗时的 `handle` 结束后才处理配置帧。

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

在“设置 → Agent → 插件管理”导入 ZIP，启用当前会话，再从聊天右下角的插件按钮打开。源码仓库中可直接参考 `umeko-plugins/file-tree` 和 `umeko-plugins/git-viewer`；安装版使用导出包中的示例，在自己的工作目录中开发。

所有 Widget 管理和通信使用 `umeko_desktop` 的 `widgets.*` 操作；`plugins.import`、`plugins.login`、`plugins.resource` 等属于 Provider 插件。每个 Widget ZIP 必须包含 20 字以内的单行 `summary`、`agent.document` 指向的完整非空 Markdown，以及 `agent.methods` 公开方法清单；文档最多 64 KiB。缺少这些材料时安装会被拒绝。

Widget 清单可选 `icon`：填写 `"terminal"`、`"folder"`、`"branch"`、`"code"`、`"pet"` 等内置名称，或 `{"path":"assets/icon.svg"}` 使用包内图标。插件管理的“内置图标”可以预览并复制清单配置；SDK 的 `umeko_plugin_sdk/icons.json` 列出全部 21 个选项。未填写时使用通用插件图标。自带图标最多 512 KiB，支持 SVG/PNG/WebP/JPEG。

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

调用立即返回 `accepted`、`requestId`、`jobId`。用 `widgets.result` 的 `requestId` 查询到 `completed` 或 `failed`，其中 `result` 包含 `{ok,result}` 或 `{ok:false,error}`，`updates` 包含该 Widget 在此请求期间推送的消息。也可用 `jobs.get` 观察最终状态。默认调用超时 20 秒，可通过 `timeoutMs` 调整为 1–120 秒；超时会停止该插件进程。最多保留 64 项请求；应用退出后未完成的调用不会恢复。

会话级 Widget 调用绑定当前显示的主会话。应用级插件也接受后台运行的其他聊天发起的调用，每次调用的参数、工作区、结果和更新都绑定发起它的聊天，只有该聊天能查询其结果。已激活的 Widget 会在调用时按需启动；`widgets.open` 用于有页面的插件。

用户附加 `terminal-ID-...` 终端引用时，Widget 包 ID 是 `terminal`。先读取 `widgets.docs`（`id: "terminal"`），再用 `widgets.call` 的 `read`、`run`、`write`、`interrupt` 操作这个已有终端。可访问的是用户附加到本聊天的终端；命令及输出显示在同一终端中。`run` 返回提交状态；命令的输出和结束用 `read` 查看。

## Widget 如何向 Agent 提供信息

调用链是：页面 → 插件 Python → Umeko 宿主 → 当前聊天 → Pi Agent。

| 目的 | Python SDK | 实际效果 |
| --- | --- | --- |
| 让 Agent 处理一段文字 | `context.send_message(text)` | 通过聊天的普通发送流程提交；正在回复时进入后续消息队列 |
| 影响正在运行的任务 | `context.send_message(text, steering=True)` | 通过聊天的引导流程提交，沿用 Umeko 当前的打断和继续行为 |
| 提供工作区文件 | `context.attach_file(relative)` | 放入当前聊天输入框的附件列表，等待用户或后续发送动作一起发送 |
| 附加文字上下文 | `context.append_to_chat(text, session=None)` | 追加到当前目标聊天的草稿，保留已有内容，不自动发送 |
| 展示本插件页面 | `context.open_page()` | 仅当调用聊天处于前台时打开；后台调用不抢占面板 |
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

`submitted` 是插件自己返回给页面的数据，表示消息已提交；Agent 的处理结果在聊天中查看。`send_message` 和 `attach_file` 与聊天输入框的行为相同，会一并发送已有附件。实时通信使用 `notify_agent`，它与输入框草稿和附件互不影响。

## 实时消息的送达与查询

1. 插件调用 `context.notify_agent("正在检查", data={"step":1})`，SDK 返回唯一消息 ID，并自动附上当前 `context.request_id`。异步线程应先保存请求 ID，再通过 `request_id=` 显式传入。
2. Umeko 验证插件权限、激活状态和会话归属，先保存消息记录，再通过已有 Pi 进程通道推送具名的 `umeko-widget-update` 自定义消息。
3. Agent 正在运行时使用 Pi 原生 `steer`，在下一个安全处理节点送达，正在执行的命令和已发出的模型请求照常进行。空闲时默认触发新回合。`wake=False` 只注入上下文，不主动触发新回合。
4. 消息进入 Agent 上下文后回传 `delivered`；此前可为 `pending`、`sending`、`queued`，失败为 `failed`。Python 的 `Plugin.on_event("agent.delivery", data)` 可收到回执。`delivered` 表示消息已送到，业务处理结果以方法返回或插件约定的协议为准。
5. 主 Agent 无需轮询就会收到推送；之后可用 `widgets.messages` 按 `nextCursor` 增量查询，也可用 `widgets.result.updates` 一并读取请求结果和运行期间的通知。

应用级后台任务应在开始时保存 `target = context.capture_session()`，完成后使用 `context.notify_agent(..., session=target)`。调用中的 `context.request_session`、`request_id` 和 `call_source` 为线程隔离的请求上下文，额外线程需要显式传入保存的值。应用级通知需要指定目标，或能通过原请求 ID 关联到目标，否则会被拒绝。目标在捕获时确定，用户切到其他聊天时保持不变；原聊天已加载时可唤醒其后台 Agent，未加载时等待它再次加载。聊天的工作区改变后，旧目标会收到失败回执，此时需要在新目标重新发起。

每条通知文本最多 8000 字，总事件最多 32 KiB；每个 Widget 每分钟最多 60 条。每个目标聊天保留最近 100 条、最多 1 MiB 的消息记录，`historyTruncated` 标明更早记录被淘汰。应用级服务尚未投递且目标暂未加载的消息可等待它再次加载；应用退出或进程中断后，已尝试但未确认的消息标为 `interrupted`，不会自动重放。任务结果来自方法返回或插件文档中明确约定的结构化协议。

## Widget 如何读取 Umeko 的信息

| 接口 | 数据与更新方式 |
| --- | --- |
| `sdk.session` / `context.session` | 当前会话 `id`、实例 `token`、标题、工作区、忙碌状态；宿主随会话变化同步 |
| `session.read` 权限 | 额外提供最近 8 条消息的角色和文本，每条最多 2000 字符 |
| `sdk.config` / `context.config` | 按插件 schema 验证后的配置 |
| `sdk.colors`、`sdk.scale`、`sdk.language`、`sdk.active` | 页面主题、字号缩放、当前界面语言（`zh` / `en`）和当前是否可交互 |
| `sdk.chatMessageComponent` | 聊天侧栏页面的宿主消息组件，复用主聊天的 Markdown、代码高亮、思考和工具过程渲染。Loader 加载后设置 `message`（含 `activity`）、`messageIndex`、`assistantName`、`portrait`、`replyPortrait`（可选）、`busy`、`last`；由 Widget 提供有界消息数据。 |
| `context.resolve_workspace(relative)` | 在授权工作区内解析文件路径，要求 `workspace.read` |
| `context.state_dir` | 按插件和会话划分的持久状态目录 |

页面调用 `sdk.call(method, arguments)` 会立即得到请求 ID，Python 处理后的结果通过 `sdk.response(id, {ok, result, error})` 异步返回。耗时读取应放在 Python，页面只做交互和展示。

Umeko 会合并聊天更新，约每 200ms 同步一次最新会话快照。QML 可用 `Connections` 监听 `sdk.sessionChanged`；Python 覆盖 `Plugin.on_event("session.changed", snapshot)` 接收快照。长时间执行的 `handle()` 会延迟该进程处理后续快照，耗时任务应可取消地在后台执行。

Agent 可调用插件公开方法传入结构化数据。插件通过 `context.publish(topic, data, session=None)` 更新当前可见页面，QML 监听 `sdk.event(topic, data)`；界面事件只送达已打开的页面，页面重新打开时从插件状态读取最新数据。事件负载最多 64 KiB。应用级共享状态可不指定 session；操作某聊天对应界面元素时传入捕获的 session，事件只在该聊天处于前台时送达。`page.visibility` 事件用于暂停和恢复隐藏页面的帧传输。

## 当前能力边界

### 应用服务管理独立会话

应用级插件可声明 `sessions.manage`，通过 `context.sessions` 管理自己的原生会话。它适合定时任务和外部任务队列：任务在独立会话中运行，与前台聊天和输入框互不影响。完整无页面示例位于导出 SDK 的 `examples/session-task-service`。

用户先停止应用，再编辑当前或隔离应用 profile 的 `settings.json`，在**顶层**为插件添加 `pluginSessionProfiles` 命名配置（这项配置通过编辑文件完成）。例如：

```json
{
  "pluginSessionProfiles": {
    "session-task-service": {
      "tasks": {
        "workspace": "/path/to/workspace",
        "model": "test-model",
        "provider": "Test provider",
        "tools": [],
        "permissionMode": "ask",
        "allowApprovals": false
      }
    }
  }
}
```

`workspace` 必须是绝对路径。`model` 填已存在的**桌面模型别名**（上游模型名称在这里无效）；选填的 `provider` 必须是已配置的 Provider ID，宿主会核对该别名确实路由到这个 Provider。两个 Provider 的别名冲突时使用唯一别名。示例值都是占位符。插件的 `acquire` 按 `profile` 名称选择配置，工作目录、模型和工具都由配置决定。

`tools` 为精确工具名列表，与桌面策略取交集；服务始终排除桌面管理工具 `umeko_desktop`、`pi` 和 `pi_commands`，保证配置无法通过管理操作被修改。其他核心工具与可选子 Agent 工具需要显式配置，并受桌面策略限制。子 Agent 运行时继承同一强制工具与权限上限，模型注册表只提供配置选定的模型。`permissionMode` 为 `ask` 或 `auto`，上限是桌面允许的权限。`allowApprovals` 默认 `false`，与工具配置相互独立；开启后插件可以注册审批处理器，逐个回应 confirm 类审批请求。

下面的代码必须在插件创建的**后台线程**执行，放在 `handle()`、构造函数或 `on_event()` 之外：

```python
import uuid

session = context.sessions.acquire("task-42", profile="tasks")
handle = session["handle"]
try:
    context.sessions.subscribe(handle)
    run = context.sessions.submit(handle, uuid.uuid4().hex, "Summarize this task.")
    result = context.sessions.wait(handle, run["runId"])
    # result: runId, status, assistantMessages, optional error
finally:
    context.sessions.release(handle)
```

| SDK 方法 | 宿主操作与结果 |
| --- | --- |
| `acquire(external_key, profile=..., namespace="default", create_if_missing=True)` | `sessions.acquire`；返回 `{handle, sessionId, created}`。外部键按插件和 namespace 隔离；保留宿主数据时可在重启后重新取得同一原生会话，旧 handle 不可复用。 |
| `submit(handle, request_id, content)` | `sessions.submit`；返回 `{runId, disposition:"started"或"queued"}`。服务按 FIFO 排队，每个任务通过已有定向提示入口启动独立回合。任务结果用 `wait` 获取。 |
| `subscribe(handle)` | `sessions.subscribe`；返回 `{subscribed:true}`，后续事件进入 `on_event("sessions.event", data)`。 |
| `wait(handle, run_id)` | `sessions.wait`；宿主只在终态回复 `{runId, status, assistantMessages, error?}`。`status` 为 `completed`、`failed` 或 `cancelled`。 |
| `cancel(handle, run_id=None)` | `sessions.cancel`；指定 run 时取消该任务，省略时取消该 handle 的活动和排队任务。 |
| `history(handle, limit=None)` | `sessions.history`；返回 `{sessionId, messages, truncated}`，按原生当前分支的顺序提供最近 `limit` 条 `{role,text,...}` 消息；默认 50，最大 200。 |
| `release(handle)` | `sessions.release`；释放当前 handle。持久外部键映射与原生历史不依赖临时 handle。 |
| `register_approval_handler(handle)` | `approvals.registerHandler`；配置允许 `allowApprovals` 时返回 `{registered:true}`。 |
| `respond_approval(handle, request_id, decision)` | `approvals.respond`；`decision` 为 `allow`、`deny` 或 `unhandled`，返回 `{accepted:bool}`；只能回应所属 handle 的待处理单次审批。 |

每个阻塞方法都支持 `timeout=None`，默认等到宿主回复或 `Context.close()`。传入秒数只限制本地等待，原生任务继续运行；要取消任务请调用 `cancel`。worker 先把 `host.response` 交给 SDK 等待器，再调用插件的 `on_event`，因此后台等待不占用事件读取线程。关闭上下文会唤醒所有本地等待。

运行时回收空闲原生会话后，宿主会在下次任务时透明恢复该会话，插件继续使用原 handle。

为保持外部键与原生会话的绑定，受管理的 Pi 会拒绝会话 new、fork、import、switch 等身份切换操作。需要另一会话时，使用新的 `externalKey` 获取它。

事件包含 `handle`、`sessionId`、`runId` 与 `type`。类型为 `assistant_text`、`stream_delta`、`tool_call`、`tool_result`、`turn_end`、`error`、`approval_request`；各类型附上相关数据。`turn_end` 同样带 `status`、`assistantMessages` 和可选 `error`。流式事件用于观察过程，终态与最终文本以 `wait` 的返回为准。工具结果是有界摘要，文本最多 8192 字符。

处理审批时，`on_event` 只保存或转交数据，由后台线程调用 `respond_approval`；也可以直接用非阻塞的 `context.request_host("approvals.respond", {...})`。插件未注册、停用、崩溃、返回 `unhandled` 或在 5 秒内没有响应时，宿主转回桌面原有审批流程；整个审批请求最多等待 120 秒，未解决则拒绝。每个审批请求都需要单独回应。

需要自行处理异步协议时，使用 `context.request_host(operation, arguments)`，并在 `on_event("host.response", data)` 接收 `{requestId, operation, ok, result}` 或失败的 `error`。此处列出的九个独立会话操作可以省略捕获的前台 `session`，前提是插件为 application 生命周期并声明了 `sessions.manage`；其他宿主操作照常绑定会话。请求 JSON 最多 16 KiB，宿主响应最多 256 KiB。`runtime/umeko-operations.json` 的 `pluginSessionOperations` 列出这组插件协议；它们供插件使用，与 Agent 调用的桌面 `operations` 分开。

停用、升级、卸载或 worker 退出时，宿主清理等待、订阅和审批处理器，并取消活动和排队任务。如果活动原生回合正在等待审批，宿主保留该回合，把审批交回桌面原有流程（超时拒绝机制照常生效），只取消排队任务。应用退出时按应用关闭流程处理。每个插件只能访问自己的 handle、外部键映射和历史。配置与事件不含 Provider 凭据。插件代码以用户的权限在本机运行，只安装可信的插件。

- Agent 收到的是正常聊天消息与已发送附件；Widget 的内部状态需要通过公开方法或消息告诉 Agent。
- 普通前台会话快照是有界摘要；需要独立任务事件和结果时，应用插件使用上面的 `sessions.manage` 协议。
- Agent 通过统一桌面工具 `umeko_desktop` 调用 Widget 公开方法和传入结构化数据。
- 快照和 SDK 不含供应商密钥、登录凭据或完整系统提示词。前台快照只包含当前聊天；应用服务的每次调用还可取得发起调用聊天的授权快照。应用服务跨聊天运行，方法结果和通知按目标聊天隔离。
- Widget 的 Python、QML 和所附程序以用户的权限在本机运行，SDK 权限只约束对宿主接口的调用；只安装可信的 Widget。

通信使用宿主生成的请求 ID、插件声明的参数 schema 和当前会话绑定。完整接口说明应放在包内的 Agent 文档中，供模型按需读取。

`sdk.queuedMessagesComponent` 复用主聊天的 `QueuedMessages` 组件。Loader 加载后设置 `controller`（`queuedMessages` 数组与 `steerQueued(id)`、`removeQueued(id)`、`editQueued(id)`、`copy(text)` 方法），可设置 `objectPrefix`、`primaryActionText`、`editEnabled`、`showSourceNames` 和 `heightLimit`。组件通过 `implicitHeight` 提供队列高度；禁用编辑时点击行触发 `inspected(message)`，供 Widget 展示只读完整消息。默认行为与主聊天一致。
