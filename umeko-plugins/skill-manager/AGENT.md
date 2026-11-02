# Skill 管理 Widget

此内置 Widget 默认启用。全局停用或在当前会话停用时，Pi 不再发现、展示或自动加载该范围内的 Skill；重新启用后按原有 Pi 配置恢复。收起右侧面板只是隐藏界面，不改变启用状态。运行中的任务保留到本轮结束，下一轮使用新状态。

此 Widget 供用户浏览工作区和全局的 Skill 文件夹。每行复选框可单独启用、禁用当前会话中的 Skill，自动保存，不影响其他聊天或 Pi 默认设置。用户禁用的 Skill 不应自动重新启用。没有 Agent 方法，也没有新建入口。双击只把文件夹作为附件放入当前聊天输入框，不自动发送；右键按整个文件夹复制、粘贴、重命名、删除、打开、编辑或预览。用户粘贴或拖入时直接导入目标分区，不覆盖同名文件夹，失败才在侧栏弹窗。重命名、删除及显式替换导入的宿主确认限制在右侧面板。

## Agent 创建和管理 Skill

使用已有文件工具处理标准 Skill 目录即可，不需要调用 Widget 管理接口或创建新工具。

- 当前调用聊天的工作区：`<workspace>/.pi/skills/<skill-name>/SKILL.md`。
- 全局：`<当前 Pi agentDir>/skills/<skill-name>/SKILL.md`。用已有 `umeko_desktop` 的 `settings.get` 查看 `config.agent.agentDir`；为空时才使用 `~/.pi/agent`。不要使用另一份系统 Pi 的目录，也不要误取其他聊天的前台工作区。

SKILL.md 是 UTF-8 Markdown，YAML frontmatter 提供 `name` 和 `description`，正文写使用指引；脚本和资源放在同一个 Skill 文件夹内。遵循 Pi 原生格式与目录发现规则。默认按 Pi 配置发现；用户可在 Widget 中为当前会话单独关闭或启用。完成文件修改后，用当前实例的 `run_pi_command` 执行 `/reload`，依任务回执核实刷新。名称、简介的索引不表示正文已全部进入上下文。
