# Umeko 使用与管理文档

这里描述的是**当前 Umeko Desktop**，适用于 Python 版和 C++ 版。Pi 是内嵌的 Agent 内核；它的供应商、认证、终端主题说明**不能替代 Umeko 的配置说明**。供应商连接、账号、模型映射、桌面主题、项目及聊天由 Umeko 管理。

Agent 入口只有一个：`config_umeko`。第一次使用先调用 `{"operation":"help"}`，再用文件读取工具打开本目录相应文档。`/help` 只提供此目录的位置，不展开整个操作清单。不要直接改写 `settings.json`，也不要安装另一份 Pi 来配置 Umeko。

- [工具协议、批量与排队](control.md)
- [添加供应商、模型和网络](providers.md)
- [制作与加载自定义供应商插件](plugins.md)
- [制作、导入和切换主题](themes.md)
- [外观、运行、上下文与资源设置](settings.md)
- [项目、会话、归档、删除与分支](sessions.md)
- [Pi 扩展、Skills 与 MCP](extensions.md)
- [API 代理、访问密钥和更新](server-updates.md)
- [全部操作及参数](operations.md)

先查询实际配置和 ID，再做用户要求的修改。没有提供的密钥不要臆造；已保存的密钥不需要读出，编辑供应商时留空保留。删除、卸载、恢复出厂、安装更新等操作应符合用户明确意图。任务正在使用的连接及会话会排队处理；`queued`、`accepted` 都不能报告为“已经完成”。

配置、插件和聊天属于当前用户配置目录，升级应用不会把它们覆盖。`settings.get` 返回当前实例的路径和配置，不应猜测另一个安装副本或另一个系统用户的数据位置。

## Windows 上运行 Python 项目命令

优先使用项目已有虚拟环境的 Python 路径；项目没有指定解释器且已安装 Windows Python Launcher 时，可用 `py -3`，例如 `py -3 -m unittest discover -s tests -v`。裸 `python` 可能命中 Microsoft Store 的应用执行别名，并提示 “Python was not found”；这不表示项目依赖缺失。可用 `py -3 -c "import sys; print(sys.executable)"` 查看该启动器实际选择的解释器。Umeko 自身的 Python 运行时不等于项目所需的 Python 环境。
