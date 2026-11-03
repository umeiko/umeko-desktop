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
预设名称不表示包含该产品的订阅登录。Claude Code / Codex 预设使用官方 API Key；Kimi Code Key 与 Moonshot 平台 Key 不同；订阅 Key 也不一定能用于按量付费接口。以所选站点和账号权限为准。
:::

## 多个账号与别名 {#multiple-accounts-and-aliases}

第一个未命名账号显示为 `Kimi`；填写别名「工作」会显示 `Kimi(工作)`；第二个未填别名的账号显示 `Kimi(2)`。同一家可添加多个账号，重复名称会被拒绝或避开。

添加账号并不会立即发起付费验证请求。模型是否可用仍取决于供应商权限；保存后在聊天的模型选择器中确认。

## 网络与模型参数 {#network-and-model-settings}

供应商卡片的小齿轮可设置系统代理、直连或自定义 HTTP(S) 代理。设置按供应商保存，不等同于 Pi 扩展的 npm 网络设置。

模型设置可调整上下文长度和视觉能力。只有上游确实支持时才开启视觉或提高窗口；客户端填写更大数字不会改变模型能力。

## 多模态模型 {#multimodal-models}

在 **设置 → 账号与供应商 → 多模态模型** 中，分别为图片、语音和视频生成选择现有账号及模型。从模型目录选择，或手填上游原始模型 ID；沿用该账号的凭据与代理、CA 设置，无须新增 Key，也没有新增厂商预设。上游服务必须支持对应生成接口和参数。

图片默认生成 `1` 张，可设置默认尺寸、质量和格式。语音需要手填供应商支持的 voice ID，默认格式为 `mp3`、速度为 `1`。每次调用都会在发送提示词或文本前请求一次权限确认，自动模式也一样；当前没有始终允许选项。

视频可设置默认时长（秒）和分辨率（如 `1280x720`），两项留空均使用供应商默认值。`video_gen` 在同一次工具调用中创建异步任务，工具栏显示排队、生成状态与供应商返回的进度百分比。点击现有停止按钮会结束轮询、放弃结果，并尽力删除供应商任务；删除失败不影响本地取消。运行中的任务不会在应用重启后恢复。

生成文件保存到当前聊天工作目录，重名时追加后缀。图片显示缩略图，音频和 MP4 视频显示可点击打开的文件卡片；仅点击时使用系统默认程序打开，不会自动播放。完成的文件卡片保存在会话历史中。Agent 收到的是文件路径和文本，不接收视频字节。

视频默认采用 [OpenAI Videos 协议](https://developers.openai.com/api/reference/resources/videos/methods/create)：`POST /videos` 创建，`GET /videos/{id}` 轮询，`GET /videos/{id}/content` 下载。OpenAI 自身已关闭该 API；需要所选供应商提供此兼容协议。其他视频任务协议由供应商插件的可选 `video` 能力扩展处理。图片理解留给尚未定案的 #49，本次没有相关控件或实现。

## 自定义供应商 {#custom-providers}

ZIP 是可执行本机代码的插件，安装前确认来源。若要开发自己的供应商，在导入窗口导出 SDK 与制作 Skill，再参考[开发与 SDK](../reference/development)。

请求失败时，打开 **查看请求详情**；共享前检查其中的提示词、代码和文件内容。密钥会脱敏，但报告仍可能包含私人数据。
