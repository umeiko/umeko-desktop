# Pi 扩展、Skills、MCP

这一部分由内嵌 Pi 负责运行，但配置仍应针对 Umeko 当前加载的 Pi 实例。`run_pi_command` 只用于原生 Pi 扩展命令；`umeko_desktop` 提供桌面 UI 对应入口。不要用系统 PATH 里的另一份 `pi`，不要修改 Pi 供应商目录来添加 Umeko 供应商。

`status.get` 查看当前扩展列表、后台管理状态和 npm 配置。`extensions.scan` 重新扫描；`extensions.enable` 传扫描结果的 `id`、`enabled`；`extensions.install` 的 `source` 接受 UI 支持的 npm/Git/本地扩展来源，`project` 指定项目范围（默认 false）。`extensions.refresh` 应用并重载，使用中的任务结束后执行。

Skills 通过 `agent.save` 的 `config.skillPaths` 配置额外路径；Pi 自身资源开关/包管理沿用当前 Pi 的 settings 机制。`run_pi_command` 支持 `pi install`、`pi remove`、`pi list`、`/reload`、`/compact`、`/session`、`/name` 和已加载扩展注册的命令。不要把所有扩展的帮助全文展开到 `/help`。

MCP：`mcp.get` 的 `scope` 是 `global` 或 `project`，返回本实例文件路径和脱敏配置。`mcp.add` 的 `text` 接受 UI 支持的 `pi mcp add ...` 命令或具名 `mcpServers` JSON 字符串；`project` 为范围。也可 `mcp.save`，传 `scope` 和完整 `config` 对象。保存是替换语义，保留其他服务器，不要用脱敏占位值覆盖真实认证配置。

`mcp.reconnect` 传 `name` 重新连接。需要登录/登出等原生 MCP 命令时用当前实例的 `run_pi_command`。异步结果在 `status.get` 和配置查询中核实；含认证信息的字段不会由管理工具原样返回。项目范围必须有实际工作目录。

Umeko 的 [Provider 插件](provider-plugins.md)和 [Widget 插件](widget-plugins.md)与这些 Pi 扩展分开管理。Provider 接入模型，Widget 扩展桌面面板与当前聊天。主题与 Pi 终端配色不同，见 themes.md。

## 子 Agent

互不依赖、范围清楚的任务可以交给内置 `subagent` 工具。使用其他模型时，先查看 [委派子代理](delegate-subagents.md) 中当前实例的完整调用名称。主 Agent 负责汇总结果并给出最终答复。
