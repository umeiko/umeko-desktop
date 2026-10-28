# Pi 扩展、Skills、MCP

这一部分由内嵌 Pi 负责运行，但配置仍应针对 Umeko 当前加载的 Pi 实例。`run_pi_command` 只用于原生 Pi 扩展命令；`config_umeko` 提供桌面 UI 对应入口。不要用系统 PATH 里的另一份 `pi`，不要修改 Pi 供应商目录来添加 Umeko 供应商。

任务缺少能力时，先查看当前工具与 `run_pi_command` 的 `pi list`，复用已安装的包；再用 `marketplace_search` 搜索 npm 中带 `pi-package` 关键词的包，并用 `marketplace_detail` 和 `marketplace_audit` 查看具体版本、功能与审计备注。工具清单或 `tool_search` 没有合适的专用工具时，即使可以用 Shell 临时替代，也先执行上述市场搜索；优先选择小而清晰、直接满足任务的包。选择合适的包后，用 `marketplace_install` 提交包名、精确版本和本次任务需要它的理由。该工具复用当前实例的安装和排队 `/reload`；收到隐藏的实际执行结果后，用新加载的工具继续原任务，无需用户再次发送消息。不要把排队或下载完成说成工具已经可用。

若软件源不支持搜索端点，搜索工具会标明使用精确包名查询；这种方式仅检查该包是否带有 `pi-package` 关键词，不能证明已搜索整个市场。找不到合适的包时，向用户说明查了什么、哪些候选不适用，以及仍缺少的能力。不要自行编写扩展作为替代。

安装权限只能由用户在输入框旁的扳手面板或设置页切换。默认每次询问；用户也可选择完全自动。两个 Agent 安装入口都执行同一权限检查。用户拒绝时不安装，准确说明被拒绝，不重复尝试。`config_umeko` 不能改安装权限，也不能绕过该检查安装扩展。审计仅为静态备注，不代表包绝对安全。

`status.get` 查看当前扩展列表、后台管理状态和 npm 配置。`extensions.scan` 重新扫描；`extensions.enable` 传扫描结果的 `id`、`enabled`。安装请用上述带权限检查的 Agent 工具；用户仍可在设置页手动安装。`extensions.refresh` 应用并重载，使用中的任务结束后执行。

Skills 通过 `agent.save` 的 `config.skillPaths` 配置额外路径；Pi 自身资源开关/包管理沿用当前 Pi 的 settings 机制。`run_pi_command` 支持 `pi install`、`pi remove`、`pi list`、`/reload`、`/compact`、`/session`、`/name` 和已加载扩展注册的命令。不要把所有扩展的帮助全文展开到 `/help`。

MCP：`mcp.get` 的 `scope` 是 `global` 或 `project`，返回本实例文件路径和脱敏配置。`mcp.add` 的 `text` 接受 UI 支持的 `pi mcp add ...` 命令或具名 `mcpServers` JSON 字符串；`project` 为范围。也可 `mcp.save`，传 `scope` 和完整 `config` 对象。保存是替换语义，保留其他服务器，不要用脱敏占位值覆盖真实认证配置。

`mcp.reconnect` 传 `name` 重新连接。需要登录/登出等原生 MCP 命令时用当前实例的 `run_pi_command`。异步结果在 `status.get` 和配置查询中核实；含认证信息的字段不会由管理工具原样返回。项目范围必须有实际工作目录。

自定义供应商插件与这些 Pi 扩展不同，见 plugins.md。主题与 Pi 终端配色不同，见 themes.md。
