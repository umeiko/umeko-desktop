# Agent Bus（智能体总线）

全局子智能体由用户在这个应用级 Widget 中管理，关闭页面不会停止它。此 Widget 不公开管理 RPC 给模型；用户创建/销毁代理、修改形象和模型，以及开启/关闭普通会话的桥接。

使用 `umeko_desktop` 的 `agent_bus.overview`、`agent_bus.dispatch`（仅全局子智能体）、`agent_bus.requests` 和 `agent_bus.reply` 进行协作。完整协议见 `help` 的 `agents` 主题。工具调用的真实宿主会话决定身份，不能通过参数指定发送者或伪造回复。
