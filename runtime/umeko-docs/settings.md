# 外观、运行与上下文设置

先 `settings.get` 读取当前状态，不直接覆盖配置文件。外观通过专用操作即时刷新：

- `appearance.language`：`language` 为 `zh` 或 `en`。首次启动按系统语言选择。
- `appearance.fontScale`：`scale` 为 0.5–2，字体和图标一起缩放。
- Python 版还可用 `appearance.fonts` 查询字体，再用 `appearance.fontFamily` 的 `family` 切换。先用 `operations.list` 判断当前版本是否提供此项。
- `appearance.sidebar`：`width` 为 200–480，`collapsed` 为布尔值。
- `themes.select`：选择内置或自定义主题，见 themes.md。
- `sessions.reasoning`：当前调用会话的思考强度，见 providers.md。

运行设置用 `agent.save` 的 `config` **局部对象**，未提及字段保留。例如：

```json
{"operation":"agent.save","arguments":{"config":{"maxTokens":16384,"autoCompaction":true}}}
```

可配置字段：`maxTokens`（256–32768，本次回答上限）、`instructions`（最多 16000 字符的自定义指令）、`autoCompaction`（布尔）、`agentDir`（Pi 用户资源目录）、`skillPaths`、`extensionPaths`（额外路径数组）。路径使用本机路径，建议绝对路径。当前任务结束后重载相关 Pi 会话，不会在工具调用中途杀掉 Agent。改配置不会裁剪原始聊天文件；长历史的显示分区与模型上下文是两回事。

`agent.recovery` 的 `enabled` 打开/关闭恢复模式；恢复模式禁用用户扩展和资源，仍保留 Umeko 内置工具。`agent.refresh` 重新扫描并应用资源。`agent.restoreFactory` 先备份，再恢复内核；只有用户要求恢复时才调用。

npm 网络配置属于 `network.npm`，`config` 字段以 `status.get` 返回的 npm 配置为依据，字段是 `npmRegistry`、`npmUserconfig`、`npmCafile`。可局部修改，未提供的字段保留，空字符串清除该覆盖。`network.testNpm` 测试连接，结果在 `status.get` 的 npmStatus。不要关闭证书验证来解决企业证书问题；优先使用系统信任或明确的 CA 文件。

更改模型连接和选择参阅 providers.md，更改 API 代理参阅 server-updates.md，MCP/扩展配置参阅 extensions.md。任务排队结果见 control.md。
