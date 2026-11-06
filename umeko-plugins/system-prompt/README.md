# 系统提示词 / System prompt

此内置 Widget 默认关闭，可在 Widget 管理中开启。目录树显示 Pi 内核、Skills、Umeko、项目指令文件及扩展实际贡献的系统提示词。复选框控制目录或段落是否生效；选择段落可编辑、保存，或确认后恢复原文。黄色表示已修改；原文更新后会保留你的编辑并提醒它基于旧版原文。未保存草稿在切换段落或刷新时保留。

This built-in Widget is off by default; enable it in Widget management. Its tree shows the system prompt contributed by Pi, Skills, Umeko, project instruction files and extensions. Checkboxes enable or disable a folder or segment. Select a segment to edit and save it, or restore its original text after confirmation. Yellow marks edited sources. Upstream updates retain your edit and mark its older original. Unsaved drafts survive selection changes and refreshes.

覆盖内容按工作区保存在应用数据中，同工作区会话共享，重启后仍保留；不会修改原始文件。恢复原文会删除对应覆盖。关闭 Widget 时不应用覆盖，没有覆盖时也不改动原有提示词。Skills 中显示的是实际注入的技能目录说明；完整技能正文和 Widget 文档仍由模型按需读取。动态扩展提示词在实际运行后显示。

Overrides are saved in application data per workspace and shared by its conversations across restarts. Source files stay unchanged. Restore removes the override. While the Widget is off, overrides are not applied; without overrides, prompt assembly stays unchanged. Skill entries show the catalog text actually injected into the system prompt. Full Skill bodies and Widget documents are still read on demand. Dynamic extension contributions appear after an actual run.

运行中的会话暂时禁止修改。界面只使用内置 host 操作，不向模型注册编辑工具。

Changes are unavailable while the session is busy. The page uses built-in host operations and registers no model-callable editing tools.

若扩展完整替换某段或整个提示词，被替换的来源会显示为暂不生效；停用对应替换段后才恢复前面的来源。覆盖内容不改变扩展原有执行顺序。

If an extension replaces a section or the whole prompt, earlier sources are marked as replaced. Disable the corresponding replacement to use those earlier sources. Overrides preserve the extensions' original execution order.
