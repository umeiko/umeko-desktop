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

`value` 为 `off` 或当前模型的 `reasoningLevels` 中的原始名称；空列表仅支持关闭。在供应商设置添加或刷新模型、打开模型弹窗或已保存模型的齿轮时，对未检测的自动模型后台排队检测。OpenAI 兼容路径先发送省略参数的基线，再逐档测量思考量；服务端元数据和错误枚举提供候选名称。启动、切换模型/会话和发送消息沿用已有检测结果。同一模型有进行中的轮次时，探测等该轮结束；聊天与探测按模型协调请求。尚未检测时可以直接以 `off` 聊天。结果按供应商和模型缓存，重启后保留；模型切换或打开会话时，失效的档位会调整到最近的可用档位。

档位和思考参数格式各有独立的自动开关。模型字段为 `reasoningLevels`（从低到高的字符串数组）、`reasoningLevelsAuto`（布尔值）、`reasoningFormat`（字符串）、`reasoningFormatAuto`（布尔值）。保存过的旧版 `reasoningLevels` 自动视为手动设置，保持原来的数量、名称与顺序；现有齿轮编辑档位也会切换为手动。手动设置优先于检测，模型刷新不会覆盖它。

格式支持 `openai`（顶层 `reasoning_effort`，off 省略）、`openai-none`（off 发送 `none`）、`chat-template`（`chat_template_kwargs.enable_thinking`，开启时另带嵌套 `reasoning_effort`）、`qwen`（顶层 `enable_thinking` 和开启时的 effort）、`deepseek`（`thinking.type: enabled/disabled` 和开启时的 effort），以及原生 Anthropic 的 `anthropic-adaptive`。独立开关格式为 `qwen-switch`、`reasoning-switch`、`deepseek-switch`、`template-thinking`，分别只发送 `enable_thinking`、`enable_reasoning`、`thinking.type`、`chat_template_kwargs.thinking`。原生 Anthropic 的力度仍映射到 `output_config.effort`，Responses 映射到 `reasoning.effort`。

自动格式检测比较同一道题在开启、关闭时的思考量和答案。原生 effort 能产生可用分档时优先保留原生格式，再寻找实际可用的关闭方式；独立开关分别尝试开启和关闭。自动缓存可分别保存开启格式和 `offFormat`。省略参数使用上游默认模式。档位确认还要求正值使用同一指标并按名称顺序递增；观察值倒序时，档位显示“未能确认”，开关结果独立判断。

检测记录 `reasoningDetection`、`reasoningFormatDetection` 保存状态、来源、请求次数和逐档测量证据。OpenAI 兼容接口用同一道短题比较省略参数、关闭和各档位，优先读取 reasoning token 数，再使用思考字符数；相同实测量合并为代表档位。能看到思考而所有设置均无变化时，保留空档位；所有请求均看不到思考时，保留兼容档位并显示“未能确认”。`degradingStyles` 保存被排除的退化方式。格式结果的 `status` 为 `on-off-verified`（观察到开关）、`cannot-disable`（本次未找到关闭方式）或 `on-not-observable`（开启效果未能确认）。`offFormat` 可记录独立的关闭方式；`offVerified` 记录本次是否观察到关闭。每种参数组合只发送一次，自动检测最多 26 次请求。旧自动缓存会按原有后台触发补测一次，手动设置继续保留。详细说明见 `docs/reasoning-detection.md`。

上游若拒绝正在使用的档位，当前轮报错并列出已知可用档位，缓存移除该档位，等该模型当前轮结束后重新检测；不会自动重发这一轮。手动重新检测也会等待同模型空闲。模型切换若排队，下一轮才使用新连接。

每个供应商的网络模式通过 `providers.network` 设置，参数 `id`、`mode`、`address`。模式 `system` 跟随系统，`direct` 不走代理，`custom` 使用指定的 HTTP/HTTPS 代理地址。非 custom 时 `address` 留空。不要把它称为独立供应商类型。

### 多模态模型选项：图片理解、图片、语音与视频生成

在 **设置 → 账号与供应商 → 多模态模型选项** 中，分别选择图片、语音、视频生成使用的现有供应商账号和模型。可以从模型目录选择，也可以手填上游原始模型 ID。生成沿用该账号的凭据、代理、CA 与错误处理，不新增厂商预设、独立 Key 或生成重试。

同一个二级页中的图片理解设置见 [辅助视觉与 analyze_image](auxiliary-vision.md)。
`settings.get` 返回当前 `config.multimodal`；用 `generation.configure` 的 `config` 参数保存生成配置，字段为 `image`、`speech` 和 `video`，结构与返回值一致。图片理解使用同页独立配置，详见辅助视觉文档。

图片默认生成 `1` 张，可选默认尺寸、质量和格式。语音必须填写供应商支持的 voice ID，默认格式为 `mp3`、速度为 `1`。模型、参数和 voice ID 是否可用取决于上游服务。

`image_gen` 必填 `prompt`，可选 `size`、`count`、`format`、`output_filename`；`voice_gen` 必填 `text`，可选 `voice`、`format`、`speed`、`output_filename`。每次发送提示词或文本前都会请求一次权限确认，自动模式也一样；当前没有始终允许选项。文件直接写入当前聊天工作目录，只接受安全文件名，只创建新文件，重名时追加后缀。聊天展示图片缩略图或可点击的音频文件卡片，不自动打开或播放。Agent 只收到路径和文本，不收到图片像素；另行读图仍遵守现有最近图片数量限制，默认 `3`。

`video_gen` 必填 `prompt`，可选字符串 `seconds`（正整数秒）、`size`（如 `1280x720`）、`output_filename`（MP4 文件名）。时长与分辨率不传时沿用视频设置，设置留空则由供应商决定。每次发送前确认一次，未配置视频账号及模型时不注册工具。创建任务、轮询状态和下载都留在同一次工具调用中；现有工具栏显示状态与百分比。停止会结束轮询，不保存或展示迟到结果，并尽力 `DELETE /videos/{id}`；删除失败不影响取消。文件保存为当前工作目录中的新 MP4，通过文件卡片点击后才由系统程序打开，会话历史保留卡片。运行中任务不跨应用重启恢复。

OpenAI 兼容接入使用 `/images/generations`，接受 `b64_json` 或 URL 图片结果；`/audio/speech` 接受二进制音频结果。视频使用 [Videos 协议](https://developers.openai.com/api/reference/resources/videos/methods/create)：`POST /videos`，`GET /videos/{id}`，`GET /videos/{id}/content`。OpenAI 自身已关闭该 API，需要所选供应商继续提供此兼容协议。插件可声明 `generationCapabilities: ["video"]` 并实现 `generate_video(model, prompt, parameters, on_progress=None)`，通过回调上报 `{id,status,progress}` 并遵守请求取消状态，返回 MP4 媒体列表；不在默认适配器中混入其他任务协议。

### 私有 CA 与证书校验失败

Python 模型请求使用系统证书信任链，并可按供应商追加可信的 PEM 根证书/中间证书。证书过期、域名不匹配或信任链校验失败时会直接显示原因，不进入网络流重试。始终保留证书与域名校验。

在供应商齿轮 →「网络设置」填写 CA 文件路径，或调用：

```json
{"operation":"providers.certificate","arguments":{"id":"供应商ID","caFile":"C:/Users/example/.umeko/certs/company-ca.pem"}}
```

传 `caFile:""` 清除此供应商的额外 CA；修改代理模式会保留已配置的 CA。保存后下一次请求生效，不修改系统证书库或其他供应商的信任配置。通用配置可使用 `UMEKO_MODEL_CA_FILE`、`NODE_EXTRA_CA_CERTS`；环境变量变更后须完全重启应用。模型、npm 安装和客户端更新下载证书分别管理。

错误详情保留底层异常链和证书校验原因。代理 CONNECT 失败与证书错误应分别排查；证书配置不会改变用户选择的代理模式，也不会自动信任服务端返回的未知证书或关闭 TLS 校验。

`models.mappings` 的 `models` 是完整映射数组，行格式包含 `provider`、`upstream`、`alias`、`contextWindow`、`contextWindowAuto`、`vision`、`visionAuto` 及上述 reasoning 配置。省略 reasoning 字段时保留原配置；这是替换操作，先读取所有供应商并保留其他映射。插件模型 ID 由刷新获取，不能在映射中凭空新增。

`providers.remove` 删除一个供应商账号，参数 `id`。插件本身继续保留，可通过插件管理单独卸载，参阅 [Provider 插件](provider-plugins.md)。
