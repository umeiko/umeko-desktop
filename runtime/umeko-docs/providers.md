# 供应商、模型和网络

Umeko 使用自己的供应商网关。不要指导用户执行 Pi `/login`、编辑 Pi `models.json` 或注册 Pi provider 来添加桌面供应商。

先用 `providers.list` 查询实际供应商和常见供应商预设。普通 OpenAI/Anthropic 兼容接口使用 `providers.save`：

```json
{"operation":"providers.save","arguments":{
  "name":"Example API","api":"openai","baseUrl":"https://api.example.com/v1",
  "key":"用户明确提供的密钥",
  "models":[{"upstream":"example-model","alias":"example-model","contextWindow":128000,"contextWindowAuto":false,"vision":false,"visionAuto":false}]
}}
```

`api` 是 `openai` 或 `anthropic`。`baseUrl` 必须是有效 HTTP/HTTPS 地址；OpenAI 常含 `/v1`。`models` 至少一个，`upstream` 是服务端模型 ID，`alias` 是桌面使用的唯一模型别名，不能有空白或与其他供应商重复。`contextWindow`、自动识别开关与图片能力可按实际模型设置。不要把“支持图片”与“支持推理强度”混为一谈。

新增省略 `id`，返回 `createdProviderIds`。编辑必须传已有 `id`；`key:""` 保留原密钥，不会清除它。只编辑 API 兼容供应商，插件账号用插件接口。编辑使用中的连接会排队。

常见供应商（如 Codex、Kimi、GLM、MiniMax 等）使用 `providers.addCommon`，传 `preset`（从查询结果取得）、`key`、可选 `alias` 和 `region`。区域为 `cn` 或 `international`，只有预设支持的区域才有效。不要混用国内站与国际站的订阅 Key。此操作沿用 UI 的默认模型和协议选择。

切换调用会话的模型：

```json
{"operation":"models.select","arguments":{"provider":"供应商ID","model":"模型alias"}}
{"operation":"sessions.reasoning","arguments":{"value":"high"}}
```

`value` 为 `off`、`low`、`high`、`max`。`off` 完全不发送 `reasoning_effort`；实际服务是否接受其他级别依其协议与模型能力。模型切换若排队，下一轮才使用新连接。

每个供应商的网络模式通过 `providers.network` 设置，参数 `id`、`mode`、`address`。模式 `system` 跟随系统，`direct` 不走代理，`custom` 使用指定的 HTTP/HTTPS 代理地址。非 custom 时 `address` 留空。不要把它称为独立供应商类型。

`models.mappings` 的 `models` 是完整映射数组，行格式包含 `provider`、`upstream`、`alias`、`contextWindow`、`contextWindowAuto`、`vision`、`visionAuto`。这是替换操作，先读取所有供应商并保留其他映射；插件模型 ID 由刷新获取，不能在映射中凭空新增。

`providers.remove` 删除一个供应商账号，参数 `id`。它不等同于卸载整个插件，参阅 [plugins.md](plugins.md)。
