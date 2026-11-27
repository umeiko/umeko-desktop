# 供应商、模型和网络

Umeko 使用自己的供应商网关，桌面供应商通过下面的 `providers.*` 操作或设置界面添加（Pi 的 `/login`、`models.json` 和 provider 注册用不到）。

先用 `providers.list` 查询实际供应商和常见供应商预设。普通 OpenAI/Anthropic 兼容接口使用 `providers.save`：

```json
{"operation":"providers.save","arguments":{
  "name":"Example API","api":"openai","baseUrl":"https://api.example.com/v1",
  "key":"用户明确提供的密钥",
  "models":[{"upstream":"example-model","alias":"example-model","contextWindow":128000,"contextWindowAuto":false,"vision":false,"visionAuto":false}]
}}
```

`api` 是 `openai` 或 `anthropic`。`baseUrl` 必须是有效 HTTP/HTTPS 地址；OpenAI 常含 `/v1`。`models` 至少一个，`upstream` 是服务端模型 ID，`alias` 是桌面使用的唯一模型别名，不含空白且在所有供应商中唯一。`contextWindow`、自动识别开关与图片能力（`vision`）可按实际模型设置；推理强度另见下文的 reasoning 字段。

新增时省略 `id`，返回 `createdProviderIds`。编辑时传已有 `id`；`key:""` 保留原密钥。`providers.save` 编辑 API 兼容供应商，插件账号用插件接口。编辑使用中的连接会排队。

常见供应商（如 Codex、Kimi、GLM、MiniMax 等）使用 `providers.addCommon`，传 `preset`（从查询结果取得）、`key`、可选 `alias` 和 `region`。区域为 `cn` 或 `international`，取预设支持的值，并与 Key 所属站点（国内站或国际站）一致。此操作沿用 UI 的默认模型和协议选择。

切换调用会话的模型：

```json
{"operation":"models.select","arguments":{"provider":"供应商ID","model":"模型alias"}}
{"operation":"sessions.reasoning","arguments":{"value":"high"}}
```

`value` 为 `off` 或当前模型的 `reasoningLevels` 中的原始名称。空列表仅支持关闭。在供应商设置添加或刷新模型、打开模型弹窗或已保存模型的齿轮时，对未检测的自动模型后台排队检测。OpenAI 兼容路径先发送省略参数的基线，再逐档测量思考量。服务端元数据和错误枚举提供候选名称。同一模型有进行中的轮次时，探测等该轮结束再开始。尚未检测时可以直接以 `off` 聊天。结果按供应商和模型缓存，重启后保留。模型切换或打开会话时，失效的档位会调整到最近的可用档位。

`apply_patch` 默认关闭。用以下操作为某个模型开启批量文件补丁，传 `enabled:false` 关闭。设置从下次聊天请求生效。

```json
{"operation":"models.applyPatch","arguments":{"provider":"供应商ID","model":"模型alias","enabled":true}}
```


档位和思考参数格式各有独立的自动开关。模型字段为 `reasoningLevels`（从低到高的字符串数组）、`reasoningLevelsAuto`（布尔值）、`reasoningFormat`（字符串）、`reasoningFormatAuto`（布尔值）。保存过的旧版 `reasoningLevels` 自动视为手动设置，保持原来的数量、名称与顺序；现有齿轮编辑档位也会切换为手动。手动设置优先于检测，模型刷新不会覆盖它。

格式支持 `openai`（顶层 `reasoning_effort`，off 省略）、`openai-none`（off 发送 `none`）、`chat-template`（`chat_template_kwargs.enable_thinking`，开启时另带嵌套 `reasoning_effort`）、`qwen`（顶层 `enable_thinking` 和开启时的 effort）、`deepseek`（`thinking.type: enabled/disabled` 和开启时的 effort），以及原生 Anthropic 的 `anthropic-adaptive`。独立开关格式为 `qwen-switch`、`reasoning-switch`、`deepseek-switch`、`template-thinking`，分别只发送 `enable_thinking`、`enable_reasoning`、`thinking.type`、`chat_template_kwargs.thinking`。原生 Anthropic 的力度仍映射到 `output_config.effort`，Responses 映射到 `reasoning.effort`。

自动格式检测比较同一道题在开启、关闭时的思考量和答案。原生 effort 能产生可用分档时优先保留原生格式，再寻找实际可用的关闭方式；独立开关分别尝试开启和关闭。自动缓存可分别保存开启格式和 `offFormat`。省略参数使用上游默认模式。档位确认还要求正值使用同一指标并按名称顺序递增；观察值倒序时，档位显示“未能确认”，开关结果独立判断。

检测记录 `reasoningDetection`、`reasoningFormatDetection` 保存状态、来源、请求次数和逐档测量证据。OpenAI 兼容接口用同一道短题比较省略参数、关闭和各档位，优先读取 reasoning token 数，再使用思考字符数；相同实测量合并为代表档位。能看到思考而所有设置均无变化时，保留空档位；所有请求均看不到思考时，保留兼容档位并显示“未能确认”。`degradingStyles` 保存被排除的退化方式。格式结果的 `status` 为 `on-off-verified`（观察到开关）、`cannot-disable`（本次未找到关闭方式）或 `on-not-observable`（开启效果未能确认）。`offFormat` 可记录独立的关闭方式；`offVerified` 记录本次是否观察到关闭。每种参数组合只发送一次，自动检测最多 26 次请求。旧自动缓存会按原有后台触发补测一次，手动设置继续保留。详细说明见 `docs/reasoning-detection.md`。

上游若拒绝正在使用的档位，当前轮报错并列出已知可用档位，缓存移除该档位，等该模型当前轮结束后重新检测；这一轮不会自动重发。手动重新检测也会等待同模型空闲。模型切换若排队，下一轮才使用新连接。

每个供应商的网络模式通过 `providers.network` 设置，参数 `id`、`mode`、`address`。模式 `system` 跟随系统，`direct` 不走代理，`custom` 使用指定的 HTTP/HTTPS 代理地址。非 custom 时 `address` 留空。网络模式是每个供应商的一项设置。

### 多模态模型选项：图片理解、图片、语音与视频生成

在 **设置 → 账号与供应商 → 多模态模型选项** 中，分别选择图片、语音、视频生成使用的现有供应商账号和模型。可以从模型目录选择，也可以手填上游原始模型 ID。生成沿用该账号的凭据、代理、CA 与错误处理。

Python 版在“图片生成 → 供应商”中提供火山方舟、阿里云百炼和自定义 OpenAI 兼容服务。平台入口显示平台名称和 Logo；生图模型在图片生成卡片中单独选择。两家预设只需填写北京地域 API Key，并提供官方申请链接，保存后启用默认模型。已有密钥不会回填到输入框，留空保存时保留。图片账号与聊天模型分开，移除当前图片账号后只清空图片生成选择，语音、视频和聊天配置保留。

火山方舟提供 Seedream 5.5、5.0 Pro、5.0 Flash、5.0 Lite、4.5 和 4.0。现代单图型号一次一张；Lite、4.5 和 4.0 使用原生组图参数，应用最多十张。4.5/4.0 仅 JPEG，其余支持 PNG/JPEG。尺寸档位随型号变化（例如 5.5 为 1K/1.5K/2K，Lite 为 2K/3K/4K）。百炼使用 DashScope 原生同步协议，提供 Qwen Image 3.0 Pro、3.0、2.1 Pro 和 2.1 Turbo，最多六张、PNG 输出。此处是已适配的目录，不代表平台全部模型或账号已开通权限。`size` 可填 `宽x高`，Qwen 请求会转换为原生尺寸格式；未填时由供应商决定。预设按型号校验数量、尺寸、比例和格式，不接受通用 `quality` 参数。模型目录参考[火山图片生成 API](https://ark.volcengine.com/region:cn-beijing/docs/image-generation-api)和[百炼 Qwen Image API](https://help.aliyun.com/zh/model-studio/qwen-image-generation-and-editing-api-reference)。

自定义服务可添加多个独立账号，填写供应商名称、Base URL、API Key 和模型 ID。Base URL 填到服务的 API 根路径（例如 `https://example.com/v1`），应用追加 `/images/generations`，使用 Bearer 认证和 OpenAI Images 请求体，支持 URL 或 `b64_json` 返回结果。添加后可在同一弹窗中编辑、换 Key 或移除；不会进入聊天模型列表。API Key、代理和下载逻辑继续由桌面后台管理。

同一个二级页中的图片理解设置见 [辅助视觉与 analyze_image](auxiliary-vision.md)。
`settings.get` 返回当前 `config.multimodal`；用 `generation.configure` 的 `config` 参数保存生成配置，字段为 `image`、`speech` 和 `video`，结构与返回值一致。图片理解使用同页独立配置，详见辅助视觉文档。

图片默认生成 `1` 张，可选默认尺寸、质量和格式。语音必须填写供应商支持的 voice ID，默认格式为 `mp3`、速度为 `1`。模型、参数和 voice ID 是否可用取决于上游服务。

`image_gen` 必填 `prompt`，可选 `size`、`count`、`format`、`output_filename`；`voice_gen` 必填 `text`，可选 `voice`、`format`、`speed`、`output_filename`。自动模式下直接生成，询问模式下发送提示词或文本前会请求确认。文件写入当前聊天工作目录，只接受安全文件名，始终创建新文件，重名时追加后缀。聊天展示图片缩略图或音频文件卡片，用户点击后打开或播放。Agent 收到文件路径和文本；需要看图时另行读取，受最近图片数量限制（默认 `3`）。

`video_gen` 必填 `prompt`，可选字符串 `seconds`（正整数秒）、`size`（如 `1280x720`）、`output_filename`（MP4 文件名）。时长与分辨率不传时沿用视频设置，设置留空则由供应商决定。每次发送前确认一次；配置了视频账号及模型后才注册此工具。创建任务、轮询状态和下载都在同一次工具调用中完成，工具栏显示状态与百分比。停止会结束轮询、丢弃之后到达的结果，并尝试 `DELETE /videos/{id}`；无论删除是否成功，取消都会完成。文件保存为当前工作目录中的新 MP4，点击文件卡片后由系统程序打开，会话历史保留卡片。运行中的任务在应用重启后不会恢复。

OpenAI 兼容接入使用 `/images/generations`，接受 `b64_json` 或 URL 图片结果；`/audio/speech` 接受二进制音频结果。视频使用 [Videos 协议](https://developers.openai.com/api/reference/resources/videos/methods/create)：`POST /videos`，`GET /videos/{id}`，`GET /videos/{id}/content`。OpenAI 自身已关闭该 API，所选供应商需要提供此兼容协议。其他视频任务协议通过插件接入：声明 `generationCapabilities: ["video"]` 并实现 `generate_video(model, prompt, parameters, on_progress=None)`，通过回调上报 `{id,status,progress}` 并遵守请求取消状态，返回 MP4 媒体列表。

### 私有 CA 与证书校验失败

Python 模型请求使用系统证书信任链，并可按供应商追加可信的 PEM 根证书/中间证书。证书过期、域名不匹配或信任链校验失败时直接显示原因，不做网络重试。证书与域名校验始终开启。

在供应商齿轮 →「网络设置」填写 CA 文件路径，或调用：

```json
{"operation":"providers.certificate","arguments":{"id":"供应商ID","caFile":"C:/Users/example/.umeko/certs/company-ca.pem"}}
```

传 `caFile:""` 清除此供应商的额外 CA；修改代理模式会保留已配置的 CA。保存后下一次请求生效，只作用于这个供应商。通用配置可使用 `UMEKO_MODEL_CA_FILE`、`NODE_EXTRA_CA_CERTS`；环境变量变更后须完全重启应用。模型、npm 安装和客户端更新下载证书分别管理。

错误详情保留底层异常链和证书校验原因。代理 CONNECT 失败与证书错误分别排查；证书配置与代理模式互相独立；信任范围是系统证书链加上已配置的 CA，服务端返回的未知证书不会被自动信任，TLS 校验始终开启。

`models.mappings` 的 `models` 是完整映射数组，行格式包含 `provider`、`upstream`、`alias`、`contextWindow`、`contextWindowAuto`、`vision`、`visionAuto` 及上述 reasoning 配置。省略 reasoning 字段时保留原配置；这是替换操作，先读取所有供应商并保留其他映射。插件模型 ID 来自 `plugins.refreshModels` 的刷新结果。

`providers.remove` 删除一个供应商账号，参数 `id`。卸载整个插件见 [Provider 插件](provider-plugins.md)。
