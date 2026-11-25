# 账号与模型供应商 {#accounts-models}

## 三种入口 {#three-entry-points}

在 **设置 → 账号与供应商** 中选择：

| 入口 | 适用情况 |
| --- | --- |
| 常见供应商 | 已有预设，只填对应 Key 和可选别名 |
| API 供应商 | 自己填写协议、Base URL、模型等参数 |
| 自定义供应商 | 导入可信的供应商 ZIP，由插件实现登录和模型服务 |

[![供应商设置的三个独立入口](/images/providers-zh.png)](/images/providers-zh.png)

*常见供应商、API 供应商、自定义供应商是独立入口。点击常见供应商的加号选择品牌。*

常见供应商包括 Claude Code、Codex、Kimi Code、DeepSeek、GLM Coding Plan 与 MiniMax 订阅。带国内/国际站点的条目使用下拉框选择；站点会一起改变 API 地址与 Key 申请链接。

[![常见供应商选择菜单](/images/provider-choices-zh.png)](/images/provider-choices-zh.png)

1. 选择品牌，例如 Kimi Code。
2. 按「申请 API Key」前往对应控制台，填写正确类型的 Key。
3. 按需填写别名，点击「添加并使用」。

[![填写 Key 与可选账号别名](/images/provider-key-zh.png)](/images/provider-key-zh.png)

::: tip 先确认 Key 的种类
常见供应商预设都通过 API Key 接入。Claude Code / Codex 预设填写官方 API Key；Kimi Code 预设填写 Kimi Code Key，它和 Moonshot 平台 Key 是两种 Key；订阅 Key 和按量付费接口各有适用范围。具体以所选站点和账号权限为准。
:::

## 多个账号与别名 {#multiple-accounts-and-aliases}

第一个未命名账号显示为 `Kimi`；填写别名「工作」会显示 `Kimi(工作)`；第二个未填别名的账号显示 `Kimi(2)`。同一家可添加多个账号：未填别名时按 `(2)`、`(3)` 依次编号；填写的别名已被占用时会提示换一个。

保存账号后，Umeko 会在后台读取该账号的模型目录，并用很小的请求检测各模型支持的推理参数。之后在聊天的模型选择器中选择模型，可用的模型由供应商权限决定。

## 网络与模型参数 {#network-and-model-settings}

供应商卡片的小齿轮可设置系统代理、直连或自定义 HTTP(S) 代理。设置按供应商保存，与 Pi 扩展的 npm 网络设置分开。

模型设置可调整上下文长度和视觉能力。模型的实际能力由上游决定，请按上游支持的范围填写这两项。

## 多模态模型选项 {#multimodal-models}

在 **设置 → 账号与供应商 → 多模态模型选项** 中，分别为图片、语音和视频生成选择现有账号及模型。从模型目录选择，或手填上游原始模型 ID；沿用该账号的凭据、代理与 CA 设置，无须另配 Key。上游服务需要支持对应的生成接口和参数。

图片默认生成 `1` 张，可设置默认尺寸、质量和格式。语音需要手填供应商支持的 voice ID，默认格式为 `mp3`、速度为 `1`。每次调用都会在发送提示词或文本前请求一次权限确认，自动模式下也是如此。

视频可设置默认时长（秒）和分辨率（如 `1280x720`），两项留空均使用供应商默认值。`video_gen` 在同一次工具调用中创建异步任务，工具栏显示排队、生成状态与供应商返回的进度百分比。点击停止按钮会结束轮询、放弃结果，并尝试删除供应商任务；无论删除是否成功，本地都会立即取消。应用重启后，运行中的视频任务不会恢复。

生成文件保存到当前聊天工作目录，重名时追加后缀。图片显示缩略图，音频和 MP4 视频显示为文件卡片，点击后用系统默认程序打开。完成的文件卡片保存在会话历史中。Agent 只收到生成文件的路径，媒体内容本身留在文件中。

视频默认采用 [OpenAI Videos 协议](https://developers.openai.com/api/reference/resources/videos/methods/create)：`POST /videos` 创建，`GET /videos/{id}` 轮询，`GET /videos/{id}/content` 下载。所选供应商需要提供这一兼容协议（OpenAI 官方已关闭该 API）。其他视频任务协议由供应商插件的可选 `video` 能力扩展处理。

同页支持辅助视觉模型、自动分析附图和按需 `analyze_image`，后两个开关可独立配置。原生视觉模型直接接收原图；已分析的历史图片复用保存的观察结果。

## 自定义供应商 {#custom-providers}

ZIP 是可执行本机代码的插件，安装前确认来源。若要开发自己的供应商，在导入窗口导出 SDK 与制作 Skill，再参考[开发与 SDK](../reference/development)。

请求失败时，打开 **查看请求详情**；共享前检查其中的提示词、代码和文件内容。密钥会脱敏，但报告仍可能包含私人数据。
