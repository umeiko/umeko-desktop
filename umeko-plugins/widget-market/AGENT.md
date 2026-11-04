# Widget 市场 / Widget Market

此页只浏览固定 GitHub Releases 发布源，搜索只过滤当前列表。沿用 Skill 管理的紧凑列表和底部详情，通过异步 Widget SDK 请求宿主执行列表、下载检查、安装、启用、打开、导入和卸载。没有 Agent 方法，不允许自定义源、直接外部打开、后台轮询或启动时联网。来源和 README 通过 `market.browse` 的固定目标打开；权限和安装确认由宿主负责。安装不会自动启用，需用户点击“启用到当前会话”；“导入本地 ZIP”使用“设置 > Agent > Widgets”的现有导入流程。校验值状态仅表示宿主报告的本次下载核对结果。

This page browses the fixed GitHub Releases source; search only filters the current list. It follows Skill manager's compact list and bottom details, using asynchronous Widget SDK calls to list, prepare, install, enable, open, import and uninstall. It exposes no Agent methods, source configuration, direct external opens, background polling or startup networking. Source and README use fixed `market.browse` targets. Umeko owns permissions and installation confirmation. Installation never enables a Widget automatically: the user chooses Enable in this chat. Import local ZIP uses Settings > Agent > Widgets. Digest status only reports Umeko's result for that download.
