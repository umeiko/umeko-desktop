# 操作与参数参考

本页由 `umeko-operations.json` 生成。语义、示例和状态处理见相应分类文档。

动态查询可用 `operations.list`，按 prefix 筛选。参数传在 arguments 中，JSON 类型直接传对象/数组。

只读及组合操作：`help`、`operations.list`、`batch`、`settings.get`、`providers.list`、`plugins.list`、`plugins.getConfig`、`themes.list`、`themes.prompt`、`projects.list`、`sessions.list`、`sessions.get`、`mcp.get`、`status.get`、`jobs.get`。

会话专用：`models.select(provider, model, sessionId?)`、`sessions.reasoning(value, sessionId?)`。缺省关联调用会话。

| operation | arguments（类型；=默认值） | 等待空闲范围 | 启动后台工作 |
| --- | --- | --- | --- |
| `providers.save` | `id: string=""`, `name: string`, `api: string`, `baseUrl: string`, `key: string=""`, `models: json` | provider | 否 |
| `providers.addCommon` | `preset: string`, `key: string`, `alias: string=""`, `region: string="cn"` | 无 | 否 |
| `providers.remove` | `id: string` | provider | 否 |
| `providers.network` | `id: string`, `mode: string`, `address: string=""` | provider | 否 |
| `providers.certificate` | `id: string`, `caFile: string=""` | provider | 否 |
| `models.mappings` | `models: json` | all | 否 |
| `themes.import` | `path: string` | 无 | 否 |
| `themes.select` | `id: string` | 无 | 否 |
| `themes.remove` | `id: string` | 无 | 否 |
| `appearance.language` | `language: string` | 无 | 否 |
| `appearance.fontScale` | `scale: number` | 无 | 否 |
| `appearance.fontFamily`（仅 python） | `family: string` | 无 | 否 |
| `appearance.sidebar` | `width: integer`, `collapsed: boolean=false` | 无 | 否 |
| `projects.add` | `paths: json` | 无 | 否 |
| `projects.open` | `id: string` | 无 | 否 |
| `projects.rename` | `id: string`, `title: string` | 无 | 否 |
| `projects.archive` | `id: string`, `archived: boolean=true` | 无 | 否 |
| `projects.remove` | `id: string` | 无 | 否 |
| `projects.fold` | `id: string` | 无 | 否 |
| `items.pin` | `kind: string`, `id: string` | 无 | 否 |
| `sessions.open` | `id: string` | 无 | 否 |
| `sessions.new` | 无 | 无 | 否 |
| `sessions.rename` | `id: string`, `title: string` | session | 是 |
| `sessions.archive` | `id: string`, `archived: boolean=true` | 无 | 否 |
| `sessions.delete` | `id: string` | session | 否 |
| `sessions.fork` | `id: string` | session | 是 |
| `sessions.export` | `id: string`, `path: string` | session | 是 |
| `workspace.set` | `path: string` | view | 否 |
| `plugins.import` | `path: string` | 无 | 否 |
| `plugins.addAccount` | `plugin: string`, `version: string` | 无 | 否 |
| `plugins.uninstall` | `plugin: string`, `version: string` | all | 否 |
| `plugins.removeAccount` | `id: string` | provider | 否 |
| `plugins.login` | `id: string`, `fields: json` | provider | 是 |
| `plugins.refreshModels` | `id: string` | provider | 是 |
| `plugins.config` | `id: string`, `config: json` | provider | 否 |
| `plugins.models` | `id: string`, `models: json` | provider | 否 |
| `plugins.resource` | `kind: string` | 无 | 否 |
| `plugins.exportResource` | `kind: string`, `path: string` | 无 | 否 |
| `extensions.scan` | 无 | 无 | 是 |
| `extensions.refresh` | 无 | all | 是 |
| `extensions.enable` | `id: string`, `enabled: boolean` | all | 是 |
| `extensions.install` | `source: string`, `project: boolean=false` | all | 是 |
| `mcp.add` | `text: string`, `project: boolean=false` | all | 是 |
| `mcp.save` | `scope: string`, `config: json` | all | 是 |
| `mcp.reconnect` | `name: string` | view | 是 |
| `network.npm` | `config: json` | all | 否 |
| `network.testNpm` | 无 | 无 | 是 |
| `agent.save` | `config: json` | view | 否 |
| `agent.refresh` | 无 | all | 是 |
| `agent.recovery` | `enabled: boolean` | all | 否 |
| `agent.restoreFactory` | 无 | all | 是 |
| `server.save` | `port: integer`, `openai: boolean=true`, `anthropic: boolean=true`, `lan: boolean=false` | 无 | 否 |
| `server.toggle` | 无 | 无 | 否 |
| `server.saveKey` | `id: string=""`, `name: string`, `key: string=""` | 无 | 否 |
| `server.enableKey` | `id: string`, `enabled: boolean` | 无 | 否 |
| `server.revokeKey` | `id: string` | 无 | 否 |
| `updates.check` | 无 | 无 | 是 |
| `updates.download` | 无 | 无 | 是 |
| `updates.cancel` | 无 | 无 | 否 |
| `updates.install` | 无 | all | 是 |
| `kernel.check` | 无 | 无 | 是 |
| `kernel.update` | 无 | all | 是 |
