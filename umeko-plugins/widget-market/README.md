# Widget 市场 / Widget Market

从 Widgets 打开，浏览 [umeko-desktop-widgets 的 GitHub Releases](https://github.com/umeiko/umeko-desktop-widgets/releases)。打开页面时优先使用十分钟内的磁盘缓存，缓存过期才请求新列表；点击“刷新”可立即请求。没有启动时联网、后台轮询、搜索、评分或自定义发布源。

点击安装或更新后，宿主下载并检查 ZIP，再显示权限、摘要核对结果和安装确认。取消后不会安装。Widget 只发起 `market.list`、`market.prepare`、`market.install`、`market.discard` 和 `market.uninstall`，不自行安装、执行下载内容或处理确认。关闭页面会尽可能丢弃待安装包。

安装后默认停用，请到 **设置 > Agent > 插件管理** 启用。需要导入本地 ZIP 时，也从这里手动导入。

Open from Widgets to browse [umeko-desktop-widgets GitHub Releases](https://github.com/umeiko/umeko-desktop-widgets/releases). Opening uses the disk cache for ten minutes, then requests a fresh list. Refresh explicitly bypasses the cache window. There is no startup networking, background polling, search, ratings or source selector.

Install or Update asks Umeko to download and validate the ZIP, then show permissions, the digest verification result and installation confirmation. Canceling does not install it. This Widget only calls `market.list`, `market.prepare`, `market.install`, `market.discard` and `market.uninstall`; it does not install or run downloaded content or provide its own confirmation. Leaving the page discards pending packages when possible.

Installed Widgets remain disabled until enabled in **Settings > Agent > Plugin Management**. Use the same settings page to import a local ZIP manually.
