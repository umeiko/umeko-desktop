# Umeko 插件

Umeko 插件分为两类，开发时先确定用途，再读取对应文档和 SDK。

## Provider 插件

接入供应商的认证、模型列表和推理接口，供 Umeko 和内嵌 Agent 使用模型。在“设置 → 账号与供应商”管理，使用 Provider SDK。`umeko_desktop` 的 `plugins.*` 操作属于这一类。

详见 [Provider 插件开发与管理](provider-plugins.md)。

## Widget 插件

扩展桌面面板或后台服务，例如文件管理器、版本管理、文件监听服务。在“设置 → Agent → 插件管理”管理，使用 `umeko_plugin_sdk`。`session` 生命周期跟随聊天，`application` 生命周期跨聊天常驻；由宿主按请求及目标聊天转发消息和数据。

详见 [Widget 插件开发与 Agent 交互](widget-plugins.md)。使用 `umeko_desktop` 的 `widgets.*` 管理、查询文档、调用方法和读取消息。先用 `widgets.list` 发现已激活或已打开的插件，再用 `widgets.docs` 获取它的完整使用文档及通信内容。Provider 的 `plugins.*` 操作保留原有含义。

Pi 扩展、Skills 和 MCP 另见 [Pi 扩展文档](extensions.md)。
