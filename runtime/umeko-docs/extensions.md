# Pi 扩展、Skills、MCP

这一部分由内嵌 Pi 负责运行，但配置仍应针对 Umeko 当前加载的 Pi 实例。`run_pi_command` 只用于原生 Pi 扩展命令；`umeko_desktop` 提供桌面 UI 对应入口。不要用系统 PATH 里的另一份 `pi`，不要修改 Pi 供应商目录来添加 Umeko 供应商。

`status.get` 查看当前扩展列表、后台管理状态和 npm 配置。`extensions.scan` 重新扫描；`extensions.enable` 传扫描结果的 `id`、`enabled`；`extensions.install` 的 `source` 接受 UI 支持的 npm/Git/本地扩展来源，`project` 指定项目范围（默认 false）。`extensions.refresh` 应用并重载，使用中的任务结束后执行。

所有列出的扩展（包括 Umeko 内置扩展）都可调整启用范围。`extensions.activation` 传 `id` 和 `mode`：`global` 为全局启用，`session` 仅在当前聊天启用，`disabled` 仅在当前聊天停用。聊天覆盖不会改写 Pi 的全局或项目设置；内置扩展也会遵守原生 `extensions` 过滤规则。Pi 原生文件与命令工具的可见性可在插件管理中逐项调整。

Pi 插件管理页面提供标准 Pi、极简、默认和自定义四种会话预设。默认保留当前已配置的能力；标准 Pi 仅保留 8 个原生工具，极简保留 read/bash/edit/write，自定义可逐插件和逐工具开关。切换预设保留上次自定义配置，不更改其他会话或磁盘上的 Pi 设置。

Skills 通过 `agent.save` 的 `config.skillPaths` 配置额外路径；Pi 自身资源开关/包管理沿用当前 Pi 的 settings 机制。`run_pi_command` 支持 `pi install`、`pi remove`、`pi list`、`/reload`、`/compact`、`/session`、`/name` 和已加载扩展注册的命令。不要把所有扩展的帮助全文展开到 `/help`。

## 创建和管理 Skill 目录

Skill 是包含 `SKILL.md` 的文件夹，资源和脚本可一起放在该文件夹中。创建、编辑、复制、重命名或删除时，使用已有的文件工具处理整个目录即可，不需要额外的 Skill 创建或管理工具，也不要求用户逐个勾选附带。

- 当前工作区：`<当前工作目录>/.pi/skills/<skill-name>/SKILL.md`。以当前调用聊天的实际工作目录为准，不能把另一个聊天的前台工作区作为目标。
- 全局：`<当前 Pi agentDir>/skills/<skill-name>/SKILL.md`。先用现有的 `settings.get` 读取 `config.agent.agentDir`；配置为空时才使用 `~/.pi/agent/skills`。Umeko 可以配置独立的 Pi 目录，不要直接假定系统另装的 Pi 使用的目录就是当前实例的目录。

`SKILL.md` 使用 UTF-8 Markdown 和 YAML frontmatter，例如：

```markdown
---
name: notes-helper
description: 整理笔记并保留原始资料的出处。
---

# 笔记整理

先阅读用户指定的资料，再按主题整理。
```

沿用 Pi 的原生格式与目录发现机制。名称和简介用于发现，正文按需读取；查看列表不等于正文已经进入上下文。完成目录修改后，可通过当前实例的 `run_pi_command` 执行 `/reload` 刷新资源；以实际任务回执和发现结果核实，不调用系统 PATH 中另一份 `pi`。不要为了添加标准目录中的 Skill 覆盖整个配置文件。

## MCP

`mcp.get` 的 `scope` 是 `global` 或 `project`，返回本实例文件路径和脱敏配置。`mcp.add` 的 `text` 接受 UI 支持的 `pi mcp add ...` 命令或具名 `mcpServers` JSON 字符串；`project` 为范围。也可 `mcp.save`，传 `scope` 和完整 `config` 对象。保存是替换语义，保留其他服务器，不要用脱敏占位值覆盖真实认证配置。

`mcp.reconnect` 传 `name` 重新连接。需要登录/登出等原生 MCP 命令时用当前实例的 `run_pi_command`。异步结果在 `status.get` 和配置查询中核实；含认证信息的字段不会由管理工具原样返回。项目范围必须有实际工作目录。

Umeko 的 [Provider 插件](provider-plugins.md)和 [Widget 插件](widget-plugins.md)与这些 Pi 扩展分开管理。Provider 接入模型，Widget 扩展桌面面板与当前聊天。主题与 Pi 终端配色不同，见 themes.md。

## 后台命令

长时间运行命令时使用内置 `background_job` 工具：启动后获得任务ID，之后可以查询状态、增量读取独立输出、限时等待，或只停止该任务的进程树。普通 bash 会拒绝按程序名称或批量结束进程的命令，具体PID仍可使用。详见 [background-jobs.md](background-jobs.md)。

## 子 Agent

互不依赖、范围清楚的任务可以交给内置 `subagent` 工具。使用其他模型时，先查看 [委派子代理](delegate-subagents.md) 中当前实例的完整调用名称。主 Agent 负责汇总结果并给出最终答复。
