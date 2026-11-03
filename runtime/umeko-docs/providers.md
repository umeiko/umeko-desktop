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

### 多模态模型：图片与语音生成

在 **设置 → 账号与供应商 → 多模态模型** 中，分别选择图片、语音生成使用的现有供应商账号和模型。可以从模型目录选择，也可以手填上游原始模型 ID。生成沿用该账号的凭据、网络与错误处理，不新增厂商预设、独立 Key 或生成重试。

图片默认生成 `1` 张，可选默认尺寸、质量和格式。语音必须填写供应商支持的 voice ID，默认格式为 `mp3`、速度为 `1`。模型、参数和 voice ID 是否可用取决于上游服务。

`image_gen` 必填 `prompt`，可选 `size`、`count`、`format`、`output_filename`；`voice_gen` 必填 `text`，可选 `voice`、`format`、`speed`、`output_filename`。每次发送提示词或文本前都会请求一次权限确认，自动模式也一样；当前没有始终允许选项。文件直接写入当前聊天工作目录，只接受安全文件名，只创建新文件，重名时追加后缀。聊天展示图片缩略图或可点击的音频文件卡片，不自动打开或播放。Agent 只收到路径和文本，不收到图片像素；另行读图仍遵守现有最近图片数量限制，默认 `3`。

OpenAI 兼容接入使用 `/images/generations`，接受 `b64_json` 或 URL 图片结果；`/audio/speech` 接受二进制音频结果。视频生成暂不可用，异步任务、进度与取消留待独立 PR。图片理解留给尚未定案的 #49，本功能不增加相关控件或实现。

### 私有 CA 与证书校验失败

Python 模型请求使用系统证书信任链，并可按供应商追加可信的 PEM 根证书/中间证书。证书过期、域名不匹配或信任链校验失败时会直接显示原因，不进入网络流重试。始终保留证书与域名校验。

在供应商齿轮 →「网络设置」填写 CA 文件路径，或调用：

```json
{"operation":"providers.certificate","arguments":{"id":"供应商ID","caFile":"C:/Users/example/.umeko/certs/company-ca.pem"}}
```

传 `caFile:""` 清除此供应商的额外 CA；修改代理模式会保留已配置的 CA。保存后下一次请求生效，不修改系统证书库或其他供应商的信任配置。通用配置可使用 `UMEKO_MODEL_CA_FILE`、`NODE_EXTRA_CA_CERTS`；环境变量变更后须完全重启应用。模型、npm 安装和客户端更新下载证书分别管理。

错误详情保留底层异常链和证书校验原因。代理 CONNECT 失败与证书错误应分别排查；证书配置不会改变用户选择的代理模式，也不会自动信任服务端返回的未知证书或关闭 TLS 校验。

`models.mappings` 的 `models` 是完整映射数组，行格式包含 `provider`、`upstream`、`alias`、`contextWindow`、`contextWindowAuto`、`vision`、`visionAuto`。这是替换操作，先读取所有供应商并保留其他映射；插件模型 ID 由刷新获取，不能在映射中凭空新增。

`providers.remove` 删除一个供应商账号，参数 `id`。它不等同于卸载整个插件，参阅 [Provider 插件](provider-plugins.md)。
