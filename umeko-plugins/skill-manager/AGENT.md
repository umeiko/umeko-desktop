# Skill 管理 Widget

此 Widget 供用户浏览工作区和全局的 Skill 文件夹。没有 Agent 方法，也没有新建入口。双击只把文件夹作为附件放入当前聊天输入框，不自动发送；右键按整个文件夹复制、粘贴、重命名、删除、打开、编辑或预览。用户粘贴或拖入时直接导入目标分区，不覆盖同名文件夹，失败才在侧栏弹窗。重命名、删除及显式替换导入的宿主确认限制在右侧面板。

## Agent 创建和管理 Skill

使用已有文件工具处理标准 Skill 目录即可，不需要调用 Widget 管理接口或创建新工具。

- 当前调用聊天的工作区：`<workspace>/.pi/skills/<skill-name>/SKILL.md`。
- 全局：`<当前 Pi agentDir>/skills/<skill-name>/SKILL.md`。用已有 `umeko_desktop` 的 `settings.get` 查看 `config.agent.agentDir`；为空时才使用 `~/.pi/agent`。不要使用另一份系统 Pi 的目录，也不要误取其他聊天的前台工作区。

SKILL.md 是 UTF-8 Markdown，YAML frontmatter 提供 `name` 和 `description`，正文写使用指引；脚本和资源放在同一个 Skill 文件夹内。遵循 Pi 原生格式与目录发现规则，不用逐聊天勾选。完成文件修改后，用当前实例的 `run_pi_command` 执行 `/reload`，依任务回执核实刷新。名称、简介的索引不表示正文已全部进入上下文。
