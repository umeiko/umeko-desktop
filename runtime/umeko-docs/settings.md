# 外观、运行与上下文设置

先 `settings.get` 读取当前状态，再通过下面的操作修改。外观通过专用操作即时刷新：

- `appearance.language`：`language` 为 `zh` 或 `en`。首次启动按系统语言选择。
- `appearance.fontScale`：`scale` 为 0.5–2，字体和图标一起缩放。
- Python 版还可用 `appearance.fonts` 查询字体，再用 `appearance.fontFamily` 的 `family` 切换。先用 `operations.list` 判断当前版本是否提供此项。
- `appearance.sidebar`：`width` 为 200–480，`collapsed` 为布尔值。
- `themes.select`：选择内置或自定义主题，见 themes.md。
- `sessions.reasoning`：当前调用会话的思考强度，见 providers.md。

Python 桌面版的“设置 → Agent → Umeko Desktop”使用 `desktop.configure`。`config` 为局部对象：`autoOpenSubmissions`（布尔，默认 true）控制 submit 后是否自动打开网页/文档；关闭后内容保留在聊天，手动点击仍可打开。`webDisplay` 为 `embedded`（默认，内置预览）或 `external`（系统默认浏览器）；网页链接和本地 HTML 文件均遵循此项。配置立即保存，向当前 Agent 进程热更新，任务继续运行。外部模式下启动时跳过内置 WebView 的加载；从该模式切回内置预览后，由用户在方便时重启应用生效。

“设置 → Agent → Umeko Desktop”还提供“开机启动 Umeko”和“开机启动 API 代理”，默认均关闭。用户打开后登记当前用户的登录启动项，无需管理员权限。页面从系统注册读取开关状态；重新打开页面或启动新版本时，已启用的注册会更新为当前打包程序路径。源码运行时这两个开关不可用，并显示原因。

Windows 使用当前用户的 Run 项，macOS 使用 `~/Library/LaunchAgents`，Linux 使用 `$XDG_CONFIG_HOME/autostart`（未指定时为 `~/.config/autostart`）。两个开关共用一个登录启动项；关闭一个只撤销对应功能，两个都关闭才删除注册。登录启动时应用停留在托盘中，不显示主窗口；系统不支持托盘时最小化到任务栏；可从托盘打开或退出。手动启动总会打开应用，能取得实例锁时留下运行标记。登录启动发现同一数据目录已有运行标记时静默退出，已有实例的代理状态保持不变；进程退出遗留的锁会被忽略。如果用户在系统的启动项管理中禁用了 Umeko，需要在系统设置中重新启用。

这两个开关在桌面 UI 中设置，`desktop.configure` 的字段保持不变。开关只影响下次登录，当前代理的运行状态不变。

`chatWidthHints`（布尔，默认 true）控制“聊天区域左右展开提示”。设为 false 后，两侧的悬浮展开/收起提示立即隐藏，当前聊天宽度保持不变。可随时在设置中重新开启。

```json
{"operation":"desktop.configure","arguments":{"config":{"autoOpenSubmissions":false,"webDisplay":"external"}}}
```

运行设置用 `agent.save` 的 `config` **局部对象**，未提及字段保留。例如：

```json
{"operation":"agent.save","arguments":{"config":{"maxTokens":16384,"autoCompaction":true}}}
```

可配置字段：`maxTokens`（256–32768，本次回答上限）、`instructions`（最多 16000 字符的自定义指令）、`autoCompaction`（布尔）、`agentDir`（Pi 用户资源目录）、`skillPaths`、`extensionPaths`（额外路径数组）。路径使用本机路径，建议绝对路径。当前任务结束后重载相关 Pi 会话。改配置时原始聊天文件保持完整；长历史在界面上的分区显示与模型上下文各自独立。

`agent.recovery` 的 `enabled` 打开/关闭恢复模式；恢复模式禁用用户扩展和资源，仍保留 Umeko 内置工具。`agent.refresh` 重新扫描并应用资源。`agent.restoreFactory` 先备份，再恢复内核；只有用户要求恢复时才调用。

npm 网络配置属于 `network.npm`，`config` 字段以 `status.get` 返回的 npm 配置为依据，字段是 `npmRegistry`、`npmUserconfig`、`npmCafile`。可局部修改，未提供的字段保留，空字符串清除该覆盖。`network.testNpm` 测试连接，结果在 `status.get` 的 npmStatus。遇到企业证书问题时，使用系统信任或明确的 CA 文件（`npmCafile`），保持证书验证开启。

高级配置：在应用数据目录的 `settings.json` 中修改 `agent.maxContextImages`（整数，默认 3，最小 1），然后重启应用以加载文件中的新值。每次请求合计用户附件和工具结果中的图片；超出上限时按两张一批移除最旧图片（上限为 1 时逐张移除），因此默认保留最新 2–3 张。原始会话、聊天展示和模型之前的文字回复保持原样；移除位置的短提示提供已有附件/读取路径，原文件缺失时保存到会话文件旁的专属 `.images` 目录，可用 `read` 再看。

更改模型连接和选择参阅 providers.md，更改 API 代理参阅 server-updates.md，MCP/扩展配置参阅 extensions.md。任务排队结果见 control.md。
