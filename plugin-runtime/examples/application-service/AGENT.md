# 文件监听服务 · Agent 使用文档

简介：跨聊天监听文件并推送变化。ID：`file-watch-service`。生命周期：`application`，没有页面。

1. 用 `umeko_desktop widgets.list` 查询，`widgets.enable` 的 `{"id":"file-watch-service","enabled":true}` 启动服务，并保存随应用启动的设置。
2. 用 `widgets.call` 的 `subscribe` 方法，传 `{"path":"相对文件路径"}`，订阅本聊天工作区内的单个文件。它返回绑定的聊天 ID；更换订阅会替换本聊天旧的监听。
3. `status` 的参数为 `{}`，仅返回本调用聊天的订阅。`unsubscribe` 的参数也是 `{}`，仅取消本聊天订阅。

```json
{"operation":"widgets.call","arguments":{"id":"file-watch-service","method":"subscribe","arguments":{"path":"README.md"}}}
```

立即返回 `accepted` 和 `requestId`；使用 `widgets.result` 查询本次方法调用是否完成。文件发生变化时会另外主动发送具名 Widget 消息，`data` 包含 `path` 和 `exists`。该通知不属于某次已经结束的调用，可用 `widgets.messages` 的 `id:"file-watch-service"` 查询。消息只发给订阅时的聊天，切换到其他聊天不会改变目标。

服务在后台每 5 秒检测一次文件状态，可通过配置调整。通知默认唤醒目标聊天的主 Agent；目标聊天当前未加载时通知保留等待，不投递给正在查看的其他聊天。后台线程捕获 `context.capture_session()` 的返回值，再通过 `notify_agent(..., session=target)` 指定原目标。

服务关闭、配置修改或应用重启后，内存订阅清空。工作目录改变后需要重新订阅。重新启用服务会影响所有聊天的监听，应符合用户意图。
