# API 代理与软件更新

Umeko 的 API 代理将已配置的模型提供为 OpenAI/Anthropic 兼容服务，与供应商的出站网络代理是两件事。

`server.save` 传 `port`、`openai`、`anthropic`、`lan`；先用 settings.get 保留未改的选项。`server.toggle` 开关服务。`status.get` 返回运行状态和访问密钥摘要。

`server.saveKey` 传 `name`、可选 `id`、`key`；新增 key 为空时沿用 UI 的生成方式，结果只提供摘要，不把完整密钥读回模型。`server.enableKey` 传 `id`、`enabled`；`server.revokeKey` 撤销指定访问密钥。已有密钥不由工具导出；用户在桌面对应 UI 中查看/复制新生成的值。

`updates.check` 检查适配当前平台/标准或精简渠道的发布；`updates.download` 下载；`updates.cancel` 取消；`updates.install` 在相关任务空闲后启动安装。下载、校验、进度和错误通过原有 UI 与 `status.get` 更新。只有用户要求升级时才安装，安装会退出当前应用并启动安装器。

`kernel.check`、`kernel.update` 用于 Pi 内核，区别于整个桌面客户端升级。当前任务结束后才替换内核。

更新器保留证书、域名和 SHA-256 校验，复用系统受信任根证书；系统代理连接失败时可以尝试经过验证的直连。企业网络缺少根证书时应安装受信任的企业 CA 或使用明确的 CA 配置，不自动关闭 SSL 校验。自定义供应商出站代理见 providers.md。
