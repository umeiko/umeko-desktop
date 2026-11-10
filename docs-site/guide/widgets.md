# Widgets 与桌面宠物 {#widgets-desktop-pets}

Widget 是 Umeko 的桌面插件：可以是右侧页面、无页面的后台服务，或受限的小窗。Widget、Pi 扩展和供应商插件各有自己的 SDK 和 ZIP 格式。

## 打开和管理 {#open-and-manage}

聊天右下角的 Widgets 入口打开已启用插件。**设置 → Agent → Widgets** 中可以导入可信 ZIP、配置或停用 Widget，并导出 SDK 和示例。

[![Widget 管理与桌宠配置](/images/widgets-zh.png)](/images/widgets-zh.png)

*左侧选择 Widget，右侧查看状态和设置；顶部可导入 ZIP 或导出 SDK。当前界面的入口名称为 Widgets。*

随应用提供的 Widget 包括文件树、Git 查看器、终端、Skill 管理、Pi 插件管理与全局子智能体。不同版本的实际清单以插件管理页为准。

关闭页面和停用插件效果不同，后台任务是否继续由各 Widget 自己决定。比如全局子智能体关闭页面仍工作，停用才会停止；Pi 插件管理关闭页面会取消它发起的安装。

## 桌面宠物 {#desktop-pet}

官方桌宠默认加载但隐藏。在其插件设置中开启显示，可拖动、点击互动、使用右键菜单，并选择独立于主界面的形象。可以导入 WebP、GIF、PNG 或多动作形象 ZIP。

桌宠的显示和隐藏只影响桌面上的形象。提醒等功能在桌宠自身的设置中配置。

## 让 Agent 使用 Widget {#let-an-agent-use-a-widget}

> 打开文件树，帮我定位这个项目的配置目录。

Agent 通过 `umeko_desktop` 的 `widgets.*` 接口查询文档、打开页面或调用公开方法。第三方 Widget 只能使用它声明并经你批准的权限；应用密钥和其他后端接口对它保持关闭。

想制作自己的 Widget，可导出 SDK 与制作 Skill，按[开发指南](../reference/development)验证并打包。安装第三方插件前检查来源与权限。
