# Umeko Widget Plugin SDK · API v1

Widget 插件扩展桌面面板和当前会话；Provider 插件负责供应商认证、模型发现和推理，两者使用不同的 SDK 和安装入口。Widget 与 Pi 扩展、MCP 也分开管理。Python 和 C++ 两个桌面版使用相同的 ZIP、SDK 和 JSONL 工作进程协议；具体宿主操作以当前版本提供的接口为准。

## 包结构

```text
my-plugin/
  manifest.json
  README.md
  config.json
  config.schema.json
  scripts/plugin.py
  qml/Main.qml            # 可选；会话级和应用级均可提供页面
  bin/linux-x64/tool      # 可选：按操作系统和架构声明的程序
  bin/windows-x64/tool.exe
  vendor/                 # 可选：与目标 Python / OS / 架构兼容的依赖
```

清单范例：

```json
{
  "kind": "umeko-plugin",
  "apiVersion": 1,
  "id": "my-plugin",
  "name": "我的插件",
  "description": "插件的功能介绍",
  "summary": "向当前聊天提供项目信息",
  "author": "Your name",
  "version": "1.0.0",
  "icon": "terminal",
  "lifecycle": "session",
  "entrypoint": "scripts/plugin.py:create_plugin",
  "page": "qml/Main.qml",
  "readme": "README.md",
  "config": "config.json",
  "configSchema": "config.schema.json",
  "permissions": ["workspace.read", "session.read", "session.write"],
  "agent": {
    "document": "AGENT.md",
    "methods": {
      "greet": {"description":"向主 Agent 推送项目信息", "parameters":{"type":"object","properties":{},"additionalProperties":false}}
    }
  },
  "executables": {}
}
```

`config.json` 是非秘密的 JSON 对象，`config.schema.json` 支持 type、properties、required、additionalProperties、items、enum。账号密码和密钥不要放入配置、Markdown、公开返回值或日志。示例和 SDK ZIP 可在插件管理页面导出，导出包中包含文件树与 Git 示例。

## Widget 图标

清单中的 `icon` 可以直接选择内置图标，例如 `"icon": "terminal"`，无需提供图片。在插件管理页点击“内置图标”预览，点击某个图标即可复制对应清单配置。启动按钮、插件菜单和插件管理统一使用这个图标；不声明时使用 `puzzle`。

| 名称 | 用途 | 名称 | 用途 |
| --- | --- | --- | --- |
| `terminal` | 终端 | `folder` | 文件管理 |
| `branch` | 版本管理 | `code` | 代码 |
| `globe` | 网页 | `search` | 搜索 |
| `chat` | 聊天 | `image` | 图片 |
| `file` | 文档 | `server` | 服务 |
| `cpu` | 计算 | `layers` | 资源 |
| `grid` | 面板 | `bulb` | 灵感 |
| `sliders` | 控制 | `archive` | 归档 |
| `download` | 下载 | `lock` | 安全 |
| `hourglass` | 任务 | `puzzle` | 通用插件 |
| `pet` | 桌面宠物 | `diff` | 差异审查 |

完整列表保存在 `umeko_plugin_sdk/icons.json`。如需自带美术资源，使用 `"icon": {"path": "assets/icon.svg"}`；路径必须是包内相对路径，支持 SVG、PNG、WebP、JPEG，最多 512 KiB。自带图标保留原色；内置线条图标自动跟随宿主主题颜色。不要填写网络地址。

每个包必须提供单行 `summary`（1–20 个 Unicode 字符）和 `agent.document` 指向的非空 Markdown（最多 64 KiB）。文档应说明用途、公开方法、参数、返回值、主动消息和限制；没有 Agent 方法时也要说明使用方式。缺少这些材料会在安装前拒绝。`agent.methods` 声明 Agent 可调用的方法和参数 schema；页面自己的调用仍可使用插件内部方法。

```bash
python -m umeko_plugin_sdk validate my-plugin
python -m umeko_plugin_sdk pack my-plugin my-plugin.zip
```

在“设置 → Agent → 插件管理”导入 ZIP；会话插件勾选“在当前会话启用”，应用服务使用全局开关。导入和读取说明不执行插件入口；配置保存后的运行行为由生命周期决定。内置插件不能被第三方 ZIP 覆盖。升级请使用新的版本号；已有配置必须通过新版本 schema 校验，否则保留旧版本。卸载清除插件包和设置，不触碰会话工作目录中的文件。

## 生命周期

`lifecycle` 默认是 `session`：插件绑定当前聊天，可带右侧页面，也可作为该聊天的后台插件。切换聊天时停止；页面插件收起时停止。

`lifecycle: "application"` 声明跨聊天常驻插件；可以省略 `page` 成为后台服务，也可以提供页面，例如共享终端。导入或升级后保持停用；用户在插件管理中启用，或 Agent 按用户意图调用 `widgets.enable` 后启动。此开关持久保存，后续随应用启动运行。切换聊天、进入设置、关闭右侧面板不停止进程；停用、升级、卸载、退出应用时停止。修改已启用插件的配置会重新启动进程。进程异常停止后可重新启用重试，不因聊天更新反复重启。

应用服务每个插件只有一个工作进程，`context.state_dir` 固定为该插件的 `application` 状态目录，不按聊天划分。它仍能接收前台 `session.changed` 快照，但每次 Agent 方法调用都有独立、线程隔离的 `context.request_session`、`context.request_id` 和 `context.call_source`，指向发起调用的聊天。后台工作必须保存 `target = context.capture_session()`，使用 `notify_agent(..., session=target)` 和 `resolve_workspace(..., session=target)`；不能在任务完成时重新读取当前聊天来决定目标。

通知会回到原聊天：该聊天已加载时可唤醒其后台 Agent，未加载时保留到它再次加载；不会发送给正在查看的其他聊天。聊天工作目录改变会使旧目标引用失效，回执为 `failed`。UI 附件和预览操作只适用于当前显示的聊天，跨聊天服务通信使用 `notify_agent`。

完整可打包示例见 `examples/application-service`。它订阅指定文件，在后台检测变化并通知订阅时的聊天。应用服务最多同时启用 8 个，与每个聊天的 8 个会话插件额度分开计算。

## Python 接口

```python
from umeko_plugin_sdk import Plugin

class MyPlugin(Plugin):
    def handle(self, method, arguments):
        if method == "greet":
            data = {"workspace": str(self.context.workspace)}
            message_id = self.context.notify_agent("已读取当前项目", data=data)
            self.context.publish("project.info", data)
            return {"messageId": message_id, **data}
        return {"workspace": str(self.context.workspace)}

def create_plugin(context):
    return MyPlugin(context)
```

`context.session` 提供前台聊天的 id、token、title、workspace、busy；有 `session.read` 时还提供最近 8 条文本消息（每条最多 2000 字符）。会话实例绑定该聊天，应用实例持续接收前台快照；方法中的 `context.request_session` 固定为调用聊天，不受前台切换影响。没有 API 密钥、供应商凭据或完整系统提示词。token 是本次应用内会话实例的标识，跨应用重启需重新捕获。主会话新获得 id 时会话启用设置会随之迁移。

- `context.config`：已校验的配置。
- `context.package_dir`：安装包目录，视为只读资源。
- `context.state_dir`：会话级按插件和聊天划分，应用级使用插件固定的 `application` 持久状态目录。
- `context.resolve_workspace(relative, session=None)`：要求 `workspace.read`，校验解析后的路径处于目标聊天目录内，拒绝目录穿越和指向外部的符号链接。应用级后台线程须显式传入捕获的 session。
- `context.send_message(text, steering=False)`：要求 `session.write`，将消息发送到绑定会话，支持 steering。
- `context.append_to_chat(text, session=None)`：要求 `session.write`，追加到目标聊天的输入框草稿，保留已有文字和附件，不自动发送；仅当前显示的目标聊天接受。
- `context.open_page()`：要求 `session.write`，请求打开本插件页面；后台聊天的调用不会抢占前台面板。
- `context.attach_file(relative)`：要求 `workspace.read` 和 `session.write`，附加文件到绑定会话。
- `context.preview_file(relative)`：要求 `workspace.read`，在 Umeko 文档预览器中打开文件，替换插件面板。
- `context.reveal_file(relative)`：要求 `workspace.read`，在系统文件管理器中定位工作区内的文件；已删除文件定位到其所在文件夹。
- `context.reveal_in_explorer(relative)`：要求 `workspace.read`，打开已启用的文件树插件并定位文件。
- `context.open_with(relative)`：要求 `workspace.read`，显示系统应用选择器。
- `context.copy_files(relatives, cut=False)`：要求 `workspace.read`，把文件写入系统文件剪贴板；剪切还要求 `workspace.write`。
- `context.notify(message)`：显示简短通知。
- `context.run_executable(name, args, timeout=12, limit=524288)`：要求 `process.execute`，按清单解析程序，不使用 shell 拼接；限制执行时间、输出和进程生命周期。
- `context.cancelled`：实例停止时的取消事件；应用服务不会因切换聊天而取消。覆盖 `Plugin.close()` 时调用 `super().close()` 并停止线程和监听。

可声明能力：`workspace.read`、`workspace.write`、`session.read`、`session.write`、`process.execute`、`git.read`、`git.write`。`workspace.write` 用于文件管理器的重命名、删除和剪切。后两项用于 Git 插件自己的操作约束。宿主再次检查会话写入和文件预览事件的权限及会话 token，丢弃旧会话的晚到事件。

## Widget、Agent 与宿主的通信

页面用 `sdk.call(method, arguments)` 异步调用插件 Python 的 `handle()`，结果由 `sdk.response` 按请求 ID 返回。Python 用上述 Context 接口向 Umeko 发出消息和附件事件，再由宿主调用当前聊天的正常操作；插件不直接访问 Pi 内部对象。

- `send_message(text)` 通过普通聊天发送，Agent 忙碌时进入后续队列；`steering=True` 走当前聊天的引导流程。
- `attach_file(relative)` 只把文件放入输入框的附件列表，发送后 Agent 才会获得它。后续 `send_message` 会沿用输入框已有附件。
- `notify(message)` 只向用户显示通知，不进入 Agent 上下文。
- `sdk.session` 随宿主更新，QML 可监听 `sdk.sessionChanged`；Python 收到同步帧后替换 `context.session` 并调用 `on_event("session.changed", snapshot)`。聊天快照约每 200ms 合并同步，不是逐 token 事件；阻塞的 `handle()` 会延迟读取更新。
- `session.read` 仅提供最近 8 条、每条最多 2000 字符的文本；没有完整聊天历史或供应商凭据。
- 原有聊天发送和附加文件接口保留单向语义；双向调用使用 `widgets.call`，主动推送使用 `notify_agent`。Provider 的 `umeko_desktop plugins.*` 操作继续管理供应商插件。

Agent 使用现有的 `umeko_desktop`，无需新增工具或命令行程序：`widgets.list` 发现激活状态和文档；`widgets.docs` 返回完整文档与参数；`widgets.call` 返回 `requestId`、`jobId`，`widgets.result` 返回实际结果和该请求的 `updates`。`widgets.messages` 的 `after`/`nextCursor` 提供本会话消息历史；安装、启用、配置、打开、卸载和 SDK 导出也由 `widgets.*` 提供。

Python 的 `context.notify_agent(message, data={}, request_id=None, wake=True, session=None)` 要求 `session.write`，主动向主 Agent 推送文字和结构化数据，返回消息 ID。默认关联当前 `context.request_id`；后台线程应保存该 ID 并显式传入。应用级后台通知必须指定已捕获的 `session`，或通过原请求 ID 关联目标。每条最多 8000 字，整个事件最多 32 KiB，每个 Widget 每分钟最多 60 条。`wake=True` 在 Agent 忙碌时走 Pi 原生 steer，在安全处理节点送达；空闲时触发新回合。`wake=False` 只注入上下文，留待当前或下次回合读取。它不消耗聊天输入框的草稿和附件。

通知会同时保存到本用户配置目录的目标聊天记录中（每聊天最近 100 条、最多 1 MiB），并出现在 `widgets.messages` 和对应 `widgets.result.updates` 中。投递状态 `pending`/`sending`/`queued`/`delivered`/`failed` 可通过 `Plugin.on_event("agent.delivery", data)` 接收；`delivered` 只表示已进入 Agent 上下文，任务完成仍以方法结果或业务协议为准。同次应用运行内，服务因目标未加载而尚未投递的消息可等待该聊天再次加载；服务停止会取消尚未投递的消息，应用退出后的未确认消息也不自动重放。

`context.publish(topic, data)` 将最多 64 KiB 的 JSON 对象异步发给当前可见页面的 `sdk.event(topic, data)`。Agent 调用插件方法后可由这个接口更新界面。Python 可覆盖 `Plugin.on_event("session.changed", snapshot)` 接收会话更新；回调运行在该插件的消息线程，耗时工作应转到可取消的后台任务。

切换聊天会撤销会话级插件页面及其工作进程；应用级服务继续运行，原请求和主动通知保持原聊天归属。Agent 只能调用 `agent.methods` 公开的方法，宿主和 worker 共同校验生命周期、激活状态、参数和请求归属。使用 `context.request_id` 和结构化结果关联任务，不通过最近聊天摘要猜测状态。

可执行文件范例：

```json
{"executables":{"helper":{"windows-x64":"bin/windows-x64/helper.exe","linux-x64":"bin/linux-x64/helper","linux-arm64":"bin/linux-arm64/helper","macos-arm64":"bin/macos-arm64/helper","macos-x64":"bin/macos-x64/helper"},"git":{"system":"git"}}}
```

使用 `context.run_executable("helper", ["--version"])`；返回 `{code, text, truncated}`。系统程序只允许清单中的简单程序名，通过 PATH 查找。原生依赖必须由插件作者按目标平台随包提供，宿主不自动执行 pip 或安装程序。

应用服务在方法调用以外执行程序时，默认工作目录为固定的 `state_dir`，不依赖前台聊天。若命令属于某段聊天，传入 `session=target` 使用已捕获的工作区；会话插件及方法调用内仍以调用聊天的工作区为目录。

## QML 页面

页面根项必须声明 `required property var sdk`。宿主异步加载页面，只有当前一个插件页面被呈现。

```qml
import QtQuick
import QtQuick.Controls
Rectangle {
    required property var sdk
    color: sdk.colors.surface
    property string request: ""
    Button {
        text: "发送到会话"
        onClicked: request = sdk.call("greet", {})
    }
    Connections {
        target: sdk
        function onResponse(id, value) {
            if (id !== request) return
            // value = {ok: true, result: {...}} 或 {ok: false, error: "..."}
        }
    }
}
```

`sdk.call(method, arguments)` 立即返回请求 ID，结果通过 `sdk.response(id, value)` 异步送达。`sdk.session` 是当前绑定的会话快照；`sdk.config` 是只读的已校验配置；`sdk.colors` 提供 bg、surface、ink、muted、line、hover、accent、accentBg、danger、dark；`sdk.scale` 为字体比例；`sdk.language` 是当前界面语言（`zh` / `en`）；`sdk.active` 表示页面当前可交互；`sdk.copyText(text)` 供用户操作复制内容。不要依赖宿主内部 backend、私有 QML 组件或未公开路径。

插件管理中的 `settingsPage` 另有 `sdk.saveConfig(object)` 与 `sdk.configSaved(id,value)`，用于保存完整配置并接收结果；`sdk.config` 随保存结果更新。清单可声明 `liveConfig:true`，使已校验、已保存的配置通过 worker 的 `configure` 帧更新 `context.config` 并触发 `on_event("config.changed",config)`，保持当前进程和临时状态；未声明时保存配置仍重启服务。配置帧在当前 `handle` 返回后处理。

终端示例使用公开的 `import Umeko.Terminal 1.0` 与 `TerminalView` 原生网格组件。`input(text)`、`resized(columns,rows)` 和 `contextMenuRequested(x,y)` 传给 Python；`applyFrame(frame)` 更新有界屏幕和滚动历史。完整帧协议与 IME、选择、剪贴板接线见 `examples/terminal/qml/TerminalPane.qml`，真实 PTY 实现及 Agent 文档也随示例提供，无需启动另一份命令执行工具。

页面的打开、收起和拖动宽度复用 Umeko 现有 PID 右侧栏。网页、文档、子代理、插件四种模式互斥。会话级页面随切换会话、进入设置、关闭页面而撤销；应用级页面可以撤销后重新打开，后台进程持续运行。Python 接收 `Plugin.on_event("page.visibility", {"visible": bool})`，可暂停隐藏页面的帧传输并在打开后补发快照。

`context.publish(topic, data, session=None)` 更新可见页面，数据最多 64 KiB。应用级进程不指定 `session` 时发布共享界面状态；显式传入捕获的 `session` 时，仅该聊天处于前台才会送达，适用于按 Agent 调用选中界面元素。

## 性能与信任边界

- 包最多 128 MiB 解压数据、2048 个 ZIP 条目，拒绝绝对路径、穿越、符号链接、特殊文件、重复路径和大小写冲突。安装前完整校验。
- 每个聊天最多启用 8 个会话插件，应用级服务另有 8 个额度；每个插件最多 8 个待完成调用，初始化及默认调用 20 秒超时，管理操作 30 秒超时。单条 JSONL 返回最多 2 MiB。
- QML 在 UI 线程中执行：使用 ListView、按需加载和后台 Python；不要在 QML 中同步扫描目录或生成巨大模型。独立工作进程使 Python 查询不阻塞聊天，但**不是操作系统权限沙箱**。Python、QML 和原生程序均是用户选择执行的可信本机代码。
- 官方文件树逐层加载，默认每层 1000 项、总缓存 10000 项、可见模型 4000 项、深度 32 层；Git 状态最多 2000 项，读取差异最多 256 KiB，未跟踪文件最多 128 KiB；渲染进一步限制为 48000 字符、1000 行、每行 2000 字符。大型差异关闭高亮，并明确显示截断提示。
- 会话插件的进程和回调随聊天结束而撤销，应用服务的后台任务则持续到实例停止。所有结果保持目标聊天归属。使用 SDK 管理的进程以获得超时与清理；自行启动的线程、文件监听、进程由插件作者负责停止。

开发时务必使用临时工作目录和假数据测试错误、超时、切换会话、关闭页面、卸载和大文件行为。Git 示例不会联网推送或自动清理工作文件。

## 宿主服务（Widget Host API v1）

QML 页可用 `sdk.hostCapabilities` 检查可用接口，用
`request = sdk.requestHost(operation, arguments)` 发起请求，并在
`sdk.hostResponse(request, value)` 中接收结果。返回空字符串表示未接收请求。
不要同步等待、循环阻塞 QML，或导入宿主的 `backend`、`PiManagement`。

Python 使用 `context.host_capabilities` 和
`context.request_host(operation, arguments={}, session=target)`；返回关联 ID，
实际响应在 `Plugin.on_event("host.response", value)` 到达。`handle()` 应立即返回，
否则会堵住同一 worker 的事件读取。应用后台线程必须先捕获
`target = context.capture_session()`，禁止任务完成后重新选择前台聊天。

| 操作 | 清单权限 | 参数 / 结果 |
| --- | --- | --- |
| `pi.status` | `pi.read` | `offset` 默认 0，`limit` 默认 100、最多 200；`query` 按名称、路径或描述搜索本地清单。`details` 可指定原生 ID，仅返回该项、最多48KiB本地 Markdown、32 个已加载工具和启用覆盖项 `activationModes`。返回 `result.extensions/total/hasMore/contextCurrent/workspace/busy/status/extensionUpdate`。`contextCurrent=false` 时不返回旧工作区缓存，先扫描。 |
| `pi.network` | `pi.read` | 返回宿主显式设置的 `npmRegistry/npmUserconfig/npmCafile`，不返回 `.npmrc` 内容、代理密钥或供应商配置。空值保留 npm 的原生配置发现行为。 |
| `pi.scan` | `pi.read` | 使用当前内嵌 Pi 的原生扩展发现，返回宿主 `jobId`。不执行被发现的扩展。 |
| `pi.details` | `pi.read` | `{id}`，按需读取有大小上限的本地 README；返回异步任务，完成后用 `pi.status {details:id}` 读取。不会执行扩展代码。 |
| `pi.activation` | `pi.manage` | `{id,mode}`；`global`、`session`、`disabled` 分别为全局启用、本对话启用、本对话暂时禁用。须宿主确认；对话覆盖不改写共享 Pi 设置。 |
| `pi.checkUpdate` | `pi.read` | `{id}` 为原生扩展 ID；原生更新检查任务。 |
| `pi.enable` | `pi.manage` | `{id, enabled: boolean}`；宿主确认后调用原生启用/停用。 |
| `pi.install` | `pi.manage` | `{source, project?: boolean}`；宿主确认后走现有手动安装流程。 |
| `pi.remove` | `pi.manage` | `{id}`；宿主确认后卸载已经登记的第三方扩展包，拒绝 Pi 内置项和独立本地文件。 |
| `pi.refresh` | `pi.manage` | 宿主确认后刷新并应用原生扩展配置。 |
| `pi.cancel` | `pi.manage` | `{id:jobId}`；仅取消本 Widget 当前实例、同一聊天/工作区发起且仍运行的插件安装。不会再次弹确认。关闭 Widget 也会取消其未完成的安装。 |
| `pi.job` | `pi.read` | `{id: jobId}`；只能读取本 Widget 实例、同一聊天/工作区创建的任务。返回 `jobs[].status` 和简短的 `result.ok/error`；安装过程中附带 `progress.message/state/cancellable`；完成后用 `pi.status` 读取列表。 |

写操作始终通过宿主确认。确认后再次检查 Widget 激活状态、聊天、工作区和忙碌状态；
不自动排队到另一个项目，也不开放修改安装权限、工具权限或任意桌面操作的接口。
`accepted`/`jobId` 只是已开始，只有 `pi.job` 的 `done` 才是完成，`failed` 才是失败。
运行中的 Agent 安装应继续调用现有 `run_pi_command` 和其权限确认、排队 `/reload`；
Widget 管理接口会拒绝忙碌时的写操作，不能作为安装权限的替代路径。
公开 Agent RPC 始终拒绝 `extensions.install`；确认后的 WidgetHost 使用进程内私有
安装入口，JSON 中的 `origin` 或其他标志不能开启它。这个通道仍复用同一原生安装器和任务回执。

每实例最多 8 个待处理宿主请求、全局最多保留 128 个任务关联；请求最多 16 KiB，
响应最多 256 KiB，扩展列表分页。超过限制会拒绝请求，不静默截断文档。
未确认操作在 Widget 停止或两分钟无人确认后取消。所属 Widget 停止时，其安装任务
会收到取消信号；其他已经确认并交给宿主的原生任务可能继续运行，关闭页面或丢失
UI 回执不表示其他任务已经取消。查询权限随实例停止而撤销。
响应同时供 Python worker 和当前可见的所属页面接收；页面应按请求 ID 过滤。

### 复用内嵌 Node

清单可声明 `"executables": {"node": {"runtime": "node"}}`，再调用
`context.run_executable("node", [str(context.package_dir / "vendor/registry.mjs"), ...])`。
宿主提供其 Node 的实际路径，不依赖系统 PATH。仍需 `process.execute`，同样受执行时间、
输出和进程清理约束；不继承 `NODE_OPTIONS/NODE_PATH`。启动前用
`"node" in context.runtimes` 检查能力。只支持固定的 `node` 名称，不能指定宿主任意程序。

这只保证 Node 运行时，不保证宿主内部 npm 依赖。Widget 应随包携带自己固定版本的
JS 依赖和许可证，例如将入口与 `node_modules` 一起放在 `vendor/` 下；ESM 不依赖
`NODE_PATH`。调用 `pi.network` 获取应用的 npm 覆盖项，再交给自己的 registry 客户端，
继续让 npm 在捕获的项目中解析其正常配置。不得把完整 npm 配置或凭据写到公开结果。
应用级后台程序默认在 `state_dir` 运行；需要项目 npm 配置时还需 `workspace.read`，
并显式向 `run_executable(..., session=target)` 传入捕获的聊天。

### 精简活动订阅

需要统计扩展使用情况的 Widget 可声明 `pi.observe`。激活后在
`on_event("pi.activity", data)` 收到至多每 200ms 一批的已结束工具元数据：
`events[].kind/id/name/state/source/time/session`，以及本批 `dropped` 数量。
`source` 来自当前 Pi 资源目录，可能为空；它不是包版本或经过推断的包名。
会话 Widget 只观察绑定聊天，应用 Widget 可观察各聊天；每条携带原聊天的 token/id/workspace。
不发送工具参数、工具结果、思考、聊天正文或 token 增量，不遍历历史。

每实例最多暂存 64 条、约 64 KiB；过载会丢弃旧元数据并报告 dropped。
它适合商店最近使用/计数展示，不是完整审计日志。按工具调用 ID 去重；计数和来源归组
由 Widget 保存在 `state_dir`，不要把用户任务内容当使用记录保存。
目前订阅主会话工具的结束事件，不能把它宣称为完整子代理或历史使用统计。

可打包的 [Pi 管理示例](examples/pi-management/README.md) 演示实际异步接口与页面；
内置的精简管理 Widget 位于源码仓库 `umeko-plugins/pi-manager`，可直接参考它的可关闭页面、本地搜索和详情滚动实现。

## 官方本轮变更审查 Widget

`change-review` 是默认关闭的内置应用服务。在插件管理启用后，宿主在 Pi 原生 `agent_start` 边界等待独立 Git 基线采集，在 `agent_end`、用户中止或主 Agent 进程退出后比较并请求打开页面。关闭页面不停止采集，停用清理临时快照。仅对应当前聊天可自动打开。全应用只保留最近一轮的临时结果，下一轮开始或退出后清除；不保存历史。页面以文件树展示，点击进入 Widget 内的 diff，再返回文件树；图标、按钮和只读菜单复用官方 Git Widget。

基线是本轮开始前的工作目录，而非 HEAD，可能包含并发编辑。采集最多 5 秒、4000 文件、单文件 2 MiB、总内容 32 MiB；二进制和受限文件只显示状态。使用独立 Git 对象/索引，不改项目暂存区和历史。Git 缺失或采集失败不阻止正常 Agent 工作。详情见内置包的 README.md。
