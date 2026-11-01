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

## 自定义供应商 {#custom-providers}

ZIP 是可执行本机代码的插件，安装前确认来源。若要开发自己的供应商，在导入窗口导出 SDK 与制作 Skill，再参考[开发与 SDK](../reference/development)。

请求失败时，打开 **查看请求详情**；共享前检查其中的提示词、代码和文件内容。密钥会脱敏，但报告仍可能包含私人数据。
