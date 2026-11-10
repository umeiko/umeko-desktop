# Skills、扩展与 MCP {#skills-extensions-mcp}

## 先分清是什么 {#know-which-kind-you-need}

| 类型 | 作用 | 常见来源 |
| --- | --- | --- |
| Skill | 指导 Agent 完成某类任务的说明和资源 | 含 `SKILL.md` 的文件夹、ZIP、`.skill` |
| Pi 扩展 | 给内核增加工具、命令或行为 | npm、Git、本地扩展 |
| MCP 服务器 | 连接外部工具与资源 | 本地进程或远程服务器 |
| Widget | 桌面里的页面、应用服务或小窗 | Umeko Widget ZIP，见 [Widgets](./widgets) |

Skill 管理默认开启。标题旁的圈问号说明发现机制：可用技能的名称、简介和路径进入提示词，正文及资料按任务需要读取；双击会把文件夹附加到聊天。全局或当前会话停用该 Widget 后，对应范围不再发现和加载技能，当前任务结束后生效；收起侧栏只隐藏界面。输入 `/` 可浏览命令、已启用的 Widget 和技能，`/s` 到 `/skills` 都展开技能，可按名称或拼音筛选。

## 管理 Skill 文件夹 {#manage-skill-folders}

聊天右下角 **Widgets → Skill 管理** 分为「工作区」「全局」。工作区只作用于该项目；全局位于当前 Pi 配置目录，供使用该目录的项目使用。

[![工作区与全局两个 Skill 分区](/images/skills-zh.png)](/images/skills-zh.png)

*整包放在对应分区中管理。要导入到哪个范围，就拖入或粘贴到那个分区。*

- 单击定位，双击将整个文件夹附加到聊天，不自动发送。
- 右键可预览、编辑、定位、复制、粘贴、重命名或删除整个包。
- 把 Skill 文件夹、ZIP 或 `.skill` 直接拖到目标分区，或在该分区粘贴，可原地导入。只有失败时才弹窗；遇到重名时保留原有的包。
- 需要预览导入结果或替换重名项时，使用显式「导入」入口。

[![Skill 整包右键菜单](/images/skill-menu-zh.png)](/images/skill-menu-zh.png)

*右键处理整个 Skill 文件夹；双击附加到聊天，不会立即发送。*

Skill 的目录为 `<workspace>/.pi/skills/<name>/SKILL.md` 与 `<agentDir>/skills/<name>/SKILL.md`；默认 `agentDir` 是 `~/.pi/agent`，与 Umeko 用户数据目录是两个位置。

## 安装与查看扩展 {#install-and-inspect-extensions}

**Widgets → 插件管理** 可查看本地 Pi 扩展的说明、工具、主页、源码链接并检查更新。安装时粘贴 `pi install npm:包名`、Git 来源或本地路径，由宿主确认。

扩展可选择全局启用、本对话启用或本对话暂时禁用。工具可见性在任务与子代理结束后修改，下次运行生效。隐藏工具只影响模型能看到哪些工具；插件和 shell 仍以你的用户权限在本机运行，请只安装可信的扩展。

## 连接 MCP {#connect-mcp}

在 **设置 → Agent → Pi** 中配置 MCP，粘贴 `pi mcp add …` 或命名的 `mcpServers` JSON，选择全局或当前项目。MCP 扩展需要先启用；远程服务可能还要求自己的凭据。

[![Pi 设置中的 MCP 配置入口](/images/mcp-zh.png)](/images/mcp-zh.png)

*在 Pi 配置中搜索 MCP，找到服务器设置与添加入口。*

## 让 Agent 自己管理 {#ask-the-agent-to-manage-it}

> 帮我查看当前内嵌 Pi 已安装的扩展，解释它们提供什么工具。安装新扩展前先告诉我来源。

Umeko 的内核内嵌在当前桌面会话。Agent 通过 `run_pi_command` 在这个实例上执行 `pi install`、`pi mcp`、`/reload` 或 `/compact` 等受支持的操作。

扩展和 MCP 本地进程可以执行代码，只从可信来源安装。操作前先看说明，配置变化通常需要刷新或下一轮任务才能生效。
