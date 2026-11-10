# API 代理与软件更新

Umeko 的 API 代理将已配置的模型提供为 OpenAI/Anthropic 兼容服务；供应商的出站网络代理是另一项设置，见 providers.md。

`server.save` 传 `port`、`openai`、`anthropic`、`lan`；先用 settings.get 读取并保留未改的选项。`server.toggle` 开关服务。`status.get` 返回运行状态和访问密钥摘要。

“设置 → Agent → Umeko Desktop → 开机启动 API 代理”使下次登录时在后台启动桌面运行环境，再按现有流程启动代理。它使用已保存的端口、OpenAI/Anthropic 协议、LAN 选项和访问密钥。至少需要一个已启用的 API Key；密钥缺失、端口占用等情况与手动启动一样会拒绝启动。可从托盘打开窗口检查 API 代理状态。只打开“开机启动 Umeko”时只启动应用；两项都打开时也只启动一个实例。

`server.saveKey` 传 `name`、可选 `id`、`key`；新增时 `key` 为空则按 UI 的方式生成，结果只返回摘要。`server.enableKey` 传 `id`、`enabled`；`server.revokeKey` 撤销指定访问密钥。完整密钥由用户在桌面对应 UI 中查看和复制。

`updates.check` 检查适配当前平台/标准或精简渠道的发布；`updates.download` 下载；`updates.cancel` 取消；`updates.install` 在相关任务空闲后启动安装。下载、校验、进度和错误通过原有 UI 与 `status.get` 更新。用户要求升级时再安装；安装会退出当前应用并启动安装器。

`kernel.check`、`kernel.update` 用于 Pi 内核，与整个桌面客户端升级分开。当前任务结束后替换内核。

更新器执行证书、域名和 SHA-256 校验，使用系统受信任根证书；系统代理连接失败时可以尝试经过验证的直连。企业网络缺少根证书时，安装受信任的企业 CA 或使用明确的 CA 配置。自定义供应商出站代理见 providers.md。
