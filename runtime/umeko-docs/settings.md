# 外观、运行与上下文设置

先 `settings.get` 读取当前状态，再通过下面的操作修改。外观通过专用操作即时刷新：

- `appearance.language`：`language` 为 `zh` 或 `en`。首次启动按系统语言选择。
- `appearance.fontScale`：`scale` 为 0.3–2，字体和图标一起缩放。
- Python 版还可用 `appearance.fonts` 查询字体，再用 `appearance.fontFamily` 的 `family` 切换。先用 `operations.list` 判断当前版本是否提供此项。
- `appearance.sidebar`：`width` 为 200–480，`collapsed` 为布尔值。
- `appearance.lineSpacing`：`spacing` 为 `compact`、`standard` 或 `relaxed`，立即调整聊天正文、列表和思考内容的行距。
- `themes.select`：选择内置或自定义主题，见 themes.md。
- `sessions.reasoning`：`value` 为 `off` 或目标模型实际支持的思考强度；`sessionId` 可指定会话，省略时使用当前调用会话。
- `agent.defaultReasoning`：`value` 设置新桌面会话的默认思考强度，已有会话继续使用各自设置。模型映射中的自动思考能力设置仍通过 `models.mappings` 配置。

Python 桌面版的“设置 → Agent → Umeko Desktop”使用 `desktop.configure`。`config` 为局部对象：`autoOpenSubmissions`（布尔，默认 true）控制 submit 后是否自动打开网页/文档；关闭后内容保留在聊天，手动点击仍可打开。`webDisplay` 为 `embedded`（默认，内置预览）或 `external`（系统默认浏览器）；网页链接和本地 HTML 文件均遵循此项。配置立即保存，向当前 Agent 进程热更新，任务继续运行。外部模式下启动时跳过内置 WebView 的加载；从该模式切回内置预览后，由用户在方便时重启应用生效。

“设置 → Agent → Umeko Desktop”还提供“开机启动 Umeko”和“开机启动 API 代理”，默认均关闭。用户打开后登记当前用户的登录启动项，无需管理员权限。页面从系统注册读取开关状态；重新打开页面或启动新版本时，已启用的注册会更新为当前打包程序路径。源码运行时这两个开关不可用，并显示原因。

Windows 使用当前用户的 Run 项，macOS 使用 `~/Library/LaunchAgents`，Linux 使用 `$XDG_CONFIG_HOME/autostart`（未指定时为 `~/.config/autostart`）。两个开关共用一个登录启动项；关闭一个只撤销对应功能，两个都关闭才删除注册。登录启动时应用停留在托盘中，不显示主窗口；系统不支持托盘时最小化到任务栏；可从托盘打开或退出。手动启动总会打开应用，能取得实例锁时留下运行标记。登录启动发现同一数据目录已有运行标记时静默退出，已有实例的代理状态保持不变；进程退出遗留的锁会被忽略。如果用户在系统的启动项管理中禁用了 Umeko，需要在系统设置中重新启用。

Agent 可通过 `desktop.startup {"umeko":true,"proxy":false}` 设置这两个开关；`desktop.configure` 继续管理网页和聊天展示。开关只影响下次登录，当前代理的运行状态保持原样。页面显示系统启动项中的实际设置。

`chatWidthHints`（布尔，默认 true）控制“聊天区域左右展开提示”。设为 false 后，两侧的悬浮展开/收起提示立即隐藏，当前聊天宽度保持不变。可随时在设置中重新开启。

```json
{"operation":"desktop.configure","arguments":{"config":{"autoOpenSubmissions":false,"webDisplay":"external"}}}
```

运行设置用 `agent.save` 的 `config` **局部对象**，未提及字段保留。例如：

```json
{"operation":"agent.save","arguments":{"config":{"maxTokens":16384,"autoCompaction":true}}}
```

可配置字段：`maxTokens`（256–32768，本次回答上限）、`instructions`（最多 16000 字符的自定义指令）、`autoCompaction`（布尔）、`agentDir`（Pi 用户资源目录）、`skillPaths`、`extensionPaths`（额外路径数组）和 `maxContextImages`（正整数，默认 3）。路径使用本机路径，建议绝对路径。资源和上下文配置保存后重载相关 Pi 会话，忙碌会话在任务结束后应用。全局工具权限 `toolPermissionMode` 继续由用户在界面选择，保存后通过已有进程通道热更新。原始聊天文件保持完整；长历史在界面上的分区显示与模型上下文各自独立。

`agent.recovery` 的 `enabled` 打开/关闭恢复模式；恢复模式禁用用户扩展和资源，仍保留 Umeko 内置工具。`agent.refresh` 重新扫描并应用资源。`agent.restoreFactory` 先备份，再恢复内核；只有用户要求恢复时才调用。

npm 网络配置属于 `network.npm`，`config` 字段以 `status.get` 返回的 npm 配置为依据，字段是 `npmRegistry`、`npmUserconfig`、`npmCafile`。可局部修改，未提供的字段保留，空字符串清除该覆盖。`network.testNpm` 测试连接，结果在 `status.get` 的 npmStatus。遇到企业证书问题时，使用系统信任或明确的 CA 文件（`npmCafile`），保持证书验证开启。

`agent.maxContextImages` 可通过 `agent.save` 设置。每次请求合计用户附件和工具结果中的图片；超出上限时按两张一批移除最旧图片（上限为 1 时逐张移除），因此默认保留最新 2–3 张。原始会话、聊天展示和模型之前的文字回复保持原样；移除位置的短提示提供已有附件/读取路径，原文件缺失时保存到会话文件旁的专属 `.images` 目录，可用 `read` 再看。

Python 版还提供以下设置操作。先用 `operations.list` 查询当前应用提供的清单：

| 操作 | 参数与应用方式 |
| --- | --- |
| `sessions.cache` | `size` 为 0–2147483647 的整数，立即保存并调整空闲会话缓存。默认 3；设为 0 时仍保留当前空闲会话，运行中和等待审批的会话继续保留。 |
| `network.requestHeaders` | `headers` 是由 `id`、`name`、`value`、`enabled` 组成的数组，最多 32 项。保存后用于后续内置模型请求。`{{apiKey}}` 在发送时替换为当前供应商密钥。插件和 dsh 使用各自的请求头配置。 |
| `dsh.path` | `path` 为本机运行时路径；空字符串恢复自动查找。保存后按页面提示检查运行时。 |
| `dsh.useOwnConfig` | `enabled` 为布尔值；开启后使用 dsh 自身 ACP 配置中的模型与凭据，关闭后使用 Umeko 配置。模型来源在新 dsh 会话开始后固定。 |
| `sessions.backend` | `value` 为 `pi` 或 `dsh`，只可修改尚无会话 ID、消息且空闲的当前草稿。 |
| `sessions.dshModel` | `value` 为 dsh ACP 返回的模型选项值；用于已就绪、空闲且采用 dsh 自身配置的会话。 |
| `documents.previewMode` | `fileType` 为 `markdown` 或 `html`，`mode` 为 `source` 或 `rendered`，保存该类文档的预览偏好并应用到预览。 |

预览版安装、更新、正式版与预览版切换，以及通道重启继续由用户在“关于”页面确认。用户可以在页面查看运行前提、下载和重启的具体影响。

更改模型连接和选择参阅 providers.md，更改 API 代理参阅 server-updates.md，MCP/扩展配置参阅 extensions.md。任务排队结果见 control.md。
# Windows 命令沙箱

用 `umeko_desktop` 的 `settings.windowsSandbox` 读取隔离级别和联网状态。用 `settings.setWindowsSandbox` 提供 `enabled` 和 `allowNetwork` 两个布尔值。沙箱默认关闭。降低当前保护时，桌面会请用户确认。

要启用网络封锁，在 Agent 设置中点击「安装管理员级隔离」，并完成 Windows 的权限提示。标准用户隔离会限制写入位置，并在私有桌面运行命令。未完成管理员安装时，要求断网的命令仍在文件隔离下运行，工具结果会说明网络封锁尚未生效。管理员模式启用断网时，Windows 会阻止命令访问外部网络和本机 IPv4、IPv6 回环地址。设置应用于之后启动的命令。

沙箱开启后，用 `bash`、`powershell` 或 `background_job` 执行命令。首次执行沙箱 Bash 时，Umeko 下载并校验兼容组件，随后复用本机缓存。沙箱 PowerShell 和内置搜索可独立运行。Agent 可以继续读取共享终端的内容。共享终端里的交互输入由用户操作。

普通 Bash 可在「设置 → Agent → Umeko Desktop → Bash 工具」选择 Git for Windows。开启后，路径留空会搜索 PATH 和常见安装位置，也可以填写 Git for Windows 的 `bash.exe` 完整路径。
