# Widget 市场 / Widget Market

从 Widgets 打开，浏览 [umeko-desktop-widgets 的 GitHub Releases](https://github.com/umeiko/umeko-desktop-widgets/releases)。打开页面时优先使用十分钟内的磁盘缓存，缓存过期才请求新列表；点击“刷新”可立即请求。搜索仅过滤当前列表。没有启动时联网、后台轮询、评分或自定义发布源。

每行显示 Widget 图标、名称、简介、可用版本和状态；选择一行后，可在底部查看完整说明、本地发布日期、已安装版本、权限和校验值状态，打开 README 或卸载。来源和 README 由宿主按固定目标打开，不接受自定义网址。

点击安装或更新后，宿主下载并检查 ZIP，再显示权限、校验值核对结果和安装确认。取消后不会安装。Widget 通过异步 `market.*` 宿主接口完成列表、下载检查、安装、启用、打开、导入和卸载，不自行安装、执行下载内容或处理确认。关闭页面会尽可能丢弃待安装包。

新导入的会话 Widget 沿用手动导入行为：全局可用，但不会自动加入当前会话、出现在会话菜单或运行。点击“启用到当前会话”后才启用，随后可点击“打开”；也可到 **设置 > Agent > Widgets** 管理。应用级插件仍默认全局停用。“导入本地 ZIP”使用同一设置页的现有导入流程。

Open from Widgets to browse [umeko-desktop-widgets GitHub Releases](https://github.com/umeiko/umeko-desktop-widgets/releases). Opening uses the disk cache for ten minutes, then requests a fresh list. Refresh explicitly bypasses the cache window. Search filters the current list locally. There is no startup networking, background polling, ratings or source selector.

Each row shows its Widget icon, name, description, available version and status. Select a row for full details, the local publication date, installed version, permissions, digest status, README and uninstall action. Umeko opens the source and README using fixed targets; custom URLs are not accepted.

Install or Update asks Umeko to download and validate the ZIP, then show permissions, the digest verification result and installation confirmation. Canceling does not install it. This Widget uses asynchronous `market.*` host calls to list, prepare, install, enable, open, import and uninstall; it does not install or run downloaded content or provide its own confirmation. Leaving the page discards pending packages when possible.

New session Widgets follow manual ZIP import: globally available, but not automatically enabled in the current chat, shown in its menu or run. Choose **Enable in this chat**, then **Open**, or manage them in **Settings > Agent > Widgets**. Application plugins remain globally disabled on import. **Import local ZIP** uses the existing import flow on that settings page.
