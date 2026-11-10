# 常见问题 {#faq}

## Umeko 自带模型或免费额度吗？ {#does-umeko-include-a-model-account-or-free-credits}

Umeko 连接你自己配置的 API 或供应商插件，不附带模型账号或额度。权限、订阅条款和费用由相应服务决定。

## 和系统里的 pi 是同一个实例吗？ {#is-it-the-same-instance-as-my-system-pi}

Umeko 使用完整的 Pi 内核，它内嵌在桌面会话中，模型连接来自桌面的供应商设置。系统全局 `pi` 有自己的版本和配置。让 Agent 用 `run_pi_command` 操作内嵌 Pi，管理终端也从应用内打开。见[扩展与 MCP](./guide/skills)。

## 为什么模型说不知道某个工具？ {#why-does-the-model-not-know-a-tool}

确认对应扩展或 Widget 已安装并启用，且当前会话没有隐藏该工具；部分能力需要模型先用工具搜索，或按需读取 Widget 文档。安装到内嵌 Pi 后，等任务结束再刷新或重新加载。

## 关闭窗口后怎么还在运行？ {#why-is-the-app-still-running-after-i-close-it}

关闭按钮默认把窗口收进托盘，后台任务继续运行。右键托盘头像选择 **退出** 即可停止应用。后台任务完成时按系统通知设置提醒。见[聊天与通知](./guide/conversations)。

## 历史文件卡片能永久保存文件吗？ {#do-historical-file-cards-preserve-the-files}

卡片保存的是文件引用，打开时读取原文件。原文件移动或删除后，卡片就打不开了。重要产物请放在稳定的项目目录并做好备份。见[产物预览](./guide/artifacts)。

## Linux 为什么要另外下载网页组件？ {#why-is-there-a-separate-webpage-component-on-linux}

完整的 Qt WebEngine 单独分发，让基础安装包更小。只有网页预览需要它；Markdown、代码和文本预览直接可用。见[组件流程](./guide/artifacts#linux-webpage-component)。

## 为什么同一家服务有多个账号？ {#why-can-i-add-several-accounts-from-one-provider}

每个 Key 可以单独配置别名、区域、模型与代理。`Kimi(工作)` 和 `Kimi(2)` 是两条独立的账号配置；额度由各自 Key 所属的上游账号决定。

## Skill、插件、MCP 能自动隔离风险吗？ {#are-skills-plugins-and-mcp-automatically-sandboxed}

Pi 扩展、本地 MCP、供应商插件和 Widget 可以在本机运行代码，权限与你的用户账号相同。来源校验和宿主权限会限制部分操作；隐藏工具只影响模型能看到哪些工具。请只安装可信来源的内容。

## 数据会发送到哪里？ {#where-does-my-data-go}

配置和原生会话保存在本机。推理时，为完成任务选入的消息、工具结果或文件内容会发送到所选供应商；第三方扩展可能连接它们自己的外部服务。

## 文档里的功能为什么和我的版本不同？ {#why-does-the-documentation-differ-from-my-app}

本文档跟随 main，稳定 Release 会稍晚一些。在 **设置 → 关于** 查看版本、提交与平台，再对照 [Release](https://github.com/umeiko/umeko-desktop/releases) 或 [C++ Release](https://github.com/umeiko/umeko-desktop-cpp/releases)。页面中也会注明两个版本的差异。
