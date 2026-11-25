# Pi 管理示例

调用 `inventory` 取得 `hostRequestId`，表示已发起查询。宿主结果异步附加在原 Widget 请求的 `updates` 中，可用 `widgets.result` / `widgets.messages` 查询。这个方法只读取清单，不启动模型、不安装扩展、不改变权限。若 `contextCurrent` 为 false，请通过界面刷新列表。

运行中的 Agent 需要安装扩展时，使用当前 Pi 的 `run_pi_command`，它会保留权限确认和排队 reload。
