# 故障排查与反馈 {#troubleshooting}

先记下版本和复现步骤，再从出问题的那一部分开始检查。用户目录里保存着设置、凭据和会话，排查时保留它。

## 模型连接失败 {#model-connection-failures}

在出错消息中打开 **查看请求详情**，检查 HTTP 状态、模型 ID、Key 类型与站点。常见原因有 Key 权限不匹配、模型别名写错、区域选错、代理不可达或上游限流。

先确认同一账号在 Umeko 聊天里能正常对话，再排查其他客户端的 API 代理。请求详情中的密钥已脱敏，但可能含有提示词和代码，共享前请检查。

## 下载慢或校验失败 {#slow-downloads-or-failed-checksums}

应用更新使用系统代理。确认代理可用、磁盘空间充足，并且下载到的是安装包而不是网络网关的错误页面。SHA-256 校验失败时，重新下载，或从官方 Release 获取对应平台的完整包。

GitHub 访问不稳定时，可以换网络或在另一台设备下载后传回本机。覆盖安装时使用同一版本线、同一架构的官方安装包。

## 扩展安装失败 {#extension-installation-failures}

模型供应商的代理设置与 npm 配置分开。在 **设置 → Agent → Pi** 中搜索 npm，检查「npm 与网络」里的 registry、`.npmrc` 和 CA 设置。公司网络使用自己的证书时，在这里配置 CA 文件，保持证书验证开启。

确认包来源存在、网络可达、安装目标是当前内嵌 Pi。详细行为见[扩展指南](./guide/skills)。

## Linux 输入法 {#linux-input-methods}

Fcitx5 与中文引擎需要在当前桌面会话中运行。安装包自带与其 Qt 版本匹配的输入插件，请保留包内的插件。

先确认别的应用能输入中文；如果手动选过输入前端，检查启动环境。源码启动可使用 `UMEKO_QT_IM_MODULE=fcitx` 或 `ibus`，空值使用平台默认。反馈时请注明 X11 / Wayland、输入法与 Qt 版本。

[详细构建与验证说明](https://github.com/umeiko/umeko-desktop/blob/main/docs/linux-ime-fcitx5.md)

## 密钥环不可用 {#unavailable-keyring}

Linux 需要当前登录会话中已解锁的 Secret Service / KWallet，macOS 需要可访问的登录钥匙串。应用提示不可用时，检查桌面密钥服务是否运行，并留意系统弹窗。Umeko 只把 Key 保存在系统安全存储中，因此需要这项服务可用。

换电脑或换系统后请重新登录。Python 版与 C++ 版各用自己的配置目录。

## 扩展使内核无法启动 {#an-extension-prevents-kernel-startup}

在 **设置 → Agent → Pi → 管理与恢复** 中可恢复出厂内核。确认窗口会列出范围：恢复会备份相关 Pi 配置，启用恢复模式以跳过第三方资源，并保留项目、会话和供应商设置。

恢复前先等运行中的任务结束。能正常启动后，再逐个排查原来的扩展。

## 反馈问题 {#report-a-problem}

从 **设置 → 关于** 复制项目信息，并提交到对应版本：

[![关于页面中的版本与复制项目信息入口](/images/about-zh.png)](/images/about-zh.png)

*截图为 main 的源码演示；你的安装版会显示自己的版本、构建与来源信息。*

- [Python / Qt 问题反馈](https://github.com/umeiko/umeko-desktop/issues/new)
- [C++ / Qt 问题反馈](https://github.com/umeiko/umeko-desktop-cpp/issues/new)

请附上版本与提交号、系统及架构、稳定复现步骤、预期和实际结果、截图或短视频，以及必要的错误详情。Linux 界面问题请补充桌面环境和 X11 / Wayland。公开提交前，删除密钥、Cookie、私人对话和项目内容。
