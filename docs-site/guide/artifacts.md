# 文件、网页与产物预览 {#files-artifact-previews}

让 Agent 把做出的东西交到眼前：

> 把这次的分析保存为 Markdown，然后通过 submit 展示给我。

`submit_to_chatbox` 接受本地文件、文件夹和 HTTP(S) 地址。提交后保留卡片，原始文件仍在原处；移动或删除原文件会影响之后打开。

## 不同文件怎么显示 {#how-content-appears}

| 类型 | 查看方式 |
| --- | --- |
| 图片 | 聊天内预览；点击放大，滚轮缩放、拖动查看 |
| Markdown | 右侧切换「源码 / 渲染」 |
| 代码、TXT、日志 | 右侧文本预览，支持的语言带语法着色 |
| 本地静态 HTML | 切换「源码 / 网页」，网页模式需要 WebView |
| HTTP(S) 地址 | 单页侧边浏览器，提供前进、后退、刷新和地址栏 |
| 其他文件或目录 | 文件卡片，使用系统应用打开或在文件管理器中查看 |

Markdown 与 HTML 的模式分别记住上次选择。大文件或复杂文档只预览有界部分，可能降级为源码或纯文本；原文件不受影响。预览不是完整的 Office / PDF 阅读器。

[![Markdown 产物的渲染预览](/images/artifact-rendered-zh.png)](/images/artifact-rendered-zh.png)

*在聊天点击 report.md，右侧显示排版后的报告。顶部「源码 / 渲染」切换视图。*

[![同一份 Markdown 的源码视图](/images/artifact-source-zh.png)](/images/artifact-source-zh.png)

*切换到源码后仍是同一个文件，原始内容不会改动。*

## 卡片和侧栏 {#cards-and-the-side-pane}

单击已提交的网页卡片可打开侧栏；右键有 **打开**（系统浏览器）、**复制网址**、**附加到聊天**。本地文件右键支持复制、定位和附加。附加不会自动发送消息，也不清空现有草稿。

拖动侧栏左边缘调宽，点击关闭可释放预览。Agent 再次提交网址会替换当前页；相同网址会刷新。没有多标签页或打开空白浏览器的独立入口。

## Linux 网页组件 {#linux-webpage-component}

基础包不携带完整 Qt WebEngine。首次缺少组件时，只有网页提交工具的返回中会给 Agent 提供官方 ZIP、校验值与安装步骤；你可以把本地 ZIP 路径交给它安装，也可先用系统浏览器。

若 GitHub 下载受阻，可换可访问的网络或设备下载官方资源，再把 ZIP 带回本机。安装后在方便时手动重启；Agent 不应直接中断正在进行的工作。Markdown、代码、文本预览不需要这个组件。
