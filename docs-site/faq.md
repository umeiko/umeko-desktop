# 常见问题 {#faq}

## Umeko 自带模型或免费额度吗？ {#does-umeko-include-a-model-account-or-free-credits}

不附带模型账号或额度。请配置自己的 API 或供应商插件；权限、订阅条款和费用由相应服务决定。

## 和系统里的 pi 是同一个实例吗？ {#is-it-the-same-instance-as-my-system-pi}

Umeko 使用完整 Pi 内核，但它内嵌在桌面会话中，模型连接由桌面供应商设置注入。系统全局 `pi` 可能是另一个版本或配置。让 Agent 使用 `run_pi_command`，管理终端也应从应用内打开。[扩展与 MCP](./guide/skills)。

## 为什么模型说不知道某个工具？ {#why-does-the-model-not-know-a-tool}

先确认对应扩展或 Widget 已安装、启用，当前会话没有隐藏该工具；部分能力需要工具搜索或按需读取 Widget 文档。等待任务结束后刷新或重新加载，不要只往系统全局 Pi 安装。

## 关闭窗口后怎么还在运行？ {#why-is-the-app-still-running-after-i-close-it}

关闭按钮默认收进托盘。右键托盘头像选择 **退出** 才会停止应用。后台任务完成会按系统通知设置提醒。[聊天与通知](./guide/conversations)。

## 历史文件卡片能永久保存文件吗？ {#do-historical-file-cards-preserve-the-files}

卡片保存引用，不复制文件内容。删除或移动原文件会使引用失效。重要产物请保存在稳定的项目目录并自行备份。[产物预览](./guide/artifacts)。

## Linux 为什么要另外下载网页组件？ {#why-is-there-a-separate-webpage-component-on-linux}

为了让基础安装包保持较小，完整 Qt WebEngine 单独分发。只有网页需要它；Markdown、代码和文本预览照常工作。[组件流程](./guide/artifacts#linux-webpage-component)。

## 为什么同一家服务有多个账号？ {#why-can-i-add-several-accounts-from-one-provider}

每个 Key 可以独立配置别名、区域、模型与代理。`Kimi(工作)` 和 `Kimi(2)` 是不同账号，方便分开管理，并不共享上游额度。

## Skill、插件、MCP 能自动隔离风险吗？ {#are-skills-plugins-and-mcp-automatically-sandboxed}

不能。来源校验与宿主权限限制能缩小部分范围，但 Pi 扩展、本地 MCP、供应商和 Widget 可能执行本机代码。只安装可信内容；隐藏工具也不等于操作系统级沙箱。

## 数据会发送到哪里？ {#where-does-my-data-go}

配置和原生会话保存在本机。推理时，为完成任务而选入的消息、工具结果或文件内容会发送到所选供应商；第三方扩展可能使用自己的外部服务。不要把“本地历史”理解为“全部离线”。

## 文档里的功能为什么和我的版本不同？ {#why-does-the-documentation-differ-from-my-app}

本文档跟随 main；稳定 Release 可能稍晚。先在 **设置 → 关于** 查看版本、提交与平台，再对照 [Release](https://github.com/umeiko/umeko-desktop/releases) 或 [C++ Release](https://github.com/umeiko/umeko-desktop-cpp/releases)。也请留意页面中的版本差异说明。
