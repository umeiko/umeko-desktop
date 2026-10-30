# Umeko 使用与管理文档

这里描述的是**当前 Umeko Desktop**，适用于 Python 版和 C++ 版。Pi 是内嵌的 Agent 内核；它的供应商、认证、终端主题说明**不能替代 Umeko 的配置说明**。供应商连接、账号、模型映射、桌面主题、项目及聊天由 Umeko 管理。

Agent 入口只有一个：`umeko_desktop`。第一次使用先调用 `{"operation":"help"}`，再用文件读取工具打开相应文档。Umeko 的“插件”分为 **Provider 插件**和 **Widget 插件**：接入模型、登录认证查 Provider；桌面面板、与已激活插件通讯查 Widget。`help` 的 `arguments.topic` 可为 `provider`、`widget` 或 `plugins`，会定位相应文档；Widget 分类还列出当前会话已激活的 Widget 和文档路径。`/help` 只提供目录位置。不要直接改写 `settings.json`，也不要安装另一份 Pi 来配置 Umeko。

- [委派子代理：选择不同模型、正确调用名称、并行任务](delegate-subagents.md)
- [工具协议、批量与排队](control.md)
- [添加供应商、模型和网络](providers.md)
- [Provider 插件：供应商接入、认证与模型](provider-plugins.md)
- [Widget 插件：桌面面板与 Agent 交互](widget-plugins.md)
- [制作、导入和切换主题](themes.md)
- [动画形象、角色资源和第三方形象包](characters.md)
- [外观、运行、上下文与资源设置](settings.md)
- [项目、会话、归档、删除与分支](sessions.md)
- [Pi 扩展、Skills 与 MCP](extensions.md)
- [API 代理、访问密钥和更新](server-updates.md)
- [全部操作及参数](operations.md)

先查询实际配置和 ID，再做用户要求的修改。没有提供的密钥不要臆造；已保存的密钥不需要读出，编辑供应商时留空保留。删除、卸载、恢复出厂、安装更新等操作应符合用户明确意图。任务正在使用的连接及会话会排队处理；`queued`、`accepted` 都不能报告为“已经完成”。

配置、插件和聊天属于当前用户配置目录，升级应用不会把它们覆盖。`settings.get` 返回当前实例的路径和配置，不应猜测另一个安装副本或另一个系统用户的数据位置。

与 Widget 交互时先 `widgets.list`（`activeOnly:true`）发现已激活和已打开的插件，再 `widgets.docs` 读取目标插件的简短介绍、完整文档与公开方法。按文档调用 `widgets.call`，用 `widgets.result` 读取结果及期间更新。Widget 可以主动推送消息，无需轮询；`widgets.messages` 提供可按游标查询的历史记录。

## Windows 上运行 Python 项目命令

优先使用项目已有虚拟环境的 Python 路径；项目没有指定解释器且已安装 Windows Python Launcher 时，可用 `py -3`，例如 `py -3 -m unittest discover -s tests -v`。裸 `python` 可能命中 Microsoft Store 的应用执行别名，并提示 “Python was not found”；这不表示项目依赖缺失。可用 `py -3 -c "import sys; print(sys.executable)"` 查看该启动器实际选择的解释器。Umeko 自身的 Python 运行时不等于项目所需的 Python 环境。
