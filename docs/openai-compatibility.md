# OpenAI 兼容服务

Umeko 根据服务返回的错误处理参数差异。程序自动添加的可选参数被明确拒绝时，会调整该参数并重发一次。`tool_choice: required` 改为 `auto`，工具定义继续发送；其他被点名的自动参数会移出请求。

拒绝结果保存在当前配置目录的 `provider-compatibility.json`，按供应商、服务地址和模型区分。之后的自动请求会沿用这个结果。用户显式填写的字段和数值始终保留，包括 token 上限的字段名称、自定义选项、采样参数和输出格式。服务静默丢参时，请求正常完成，兼容记录只采纳明确的拒绝。

聊天网关、媒体生成、模型列表和 SDK 的标准推理请求共用 HTTP 重试。429、503 最多重试两次；支持秒数、HTTP 日期及 `retry-after-ms`。服务给出的等待时间在 30 秒以内时按其等待，超过 30 秒时展示错误。缺少有效等待值时使用从 0.5 秒起的指数退避和抖动。认证及账户操作保持单次请求。流开始返回内容后，当前传输会直接报告中断。

HTTP 重试结束后，Pi 显示最终错误并结束当前回合。后续回合恢复原有设置，普通连接中断继续沿用会话的重试流程。

应用和 Provider SDK 共用响应解析：

| 返回内容 | 处理方式 |
|---|---|
| 缺少或为空的 usage | 使用空用量；有用量时统一输入、输出 token 名称 |
| `reasoning_content`、`reasoning`、正文 `<think>` | 分成思考与正文，支持跨块标签 |
| 分段字符串或对象形式的工具参数 | 累加字符串，完整对象转成 JSON 字符串 |
| `tool_use`、`function_call`、`max_tokens`、`end_turn` 等结束值 | 转成标准工具、长度或正常结束值 |
| 空块、保活、空 data、缺少 `[DONE]` | 跳过空数据；使用结束事件或输出后的用量尾帧确认完成 |
| HTTP 200 中的 JSON 或 SSE 错误 | 保留原因、类型、参数和错误码，按失败展示 |

插件可使用 `umeko_provider_sdk.compatibility` 中的 `compatible_open` 和 `ParameterMemory`，通过 `automatic` 指定插件自行添加的字段。SDK 的 `HttpSession.request` 对标准推理和模型列表地址启用重试；自定义推理地址可传 `compatibility=True`。

| 请求入口 | 参数来源与处理 |
|---|---|
| `app/gateway.py` | 区分程序补入的字段和调用方选项；明确拒绝后恢复一次并保存结果 |
| `runtime/bridge.mjs` | 为 Pi 生成的选项附带内部来源信息，扩展修改过的值作为显式选项发送 |
| `app/openai_responses.py` | 转换历史与工具格式，保留原生字段、自定义选项和显式 token 上限；自动补入的 `store`、工具 `strict` 可单独调整 |
| `app/provider_models.py` | 模型列表及分页复用重试和错误解析 |
| `app/generation.py` | 图片数量、语音格式和语速的自动默认值可调整，已保存的媒体设置保留 |
| `umeko_provider_sdk/http.py` | 插件的标准推理地址复用传输，自定义地址可显式启用 |
| `app/dsh_backend.py` | 托管配置通过同一个本地网关；自有配置使用 DSH 的模型连接 |
| CodeArts 插件 | 使用官方服务的会话协议，模型参数由该服务管理 |

兼容文件只保存被点名的字段名称。用户选项可覆盖这些历史结果；服务地址或模型改变后使用各自的记录。响应中的对象工具参数统一序列化，后续历史转换继续使用同一表示。

思考格式与档位继续采用现有探测结果，探测请求保留原始服务回应。内建接口覆盖聊天、模型列表、图片、语音和视频。

实现参考 [OpenAI Python SDK 的 Retry-After、指数退避与抖动](https://github.com/openai/openai-python/blob/main/src/openai/_base_client.py)，以及 [OpenRouter 的 SSE 保活与流内错误说明](https://openrouter.ai/docs/api_reference/streaming)。本次覆盖见 `tests/test_gateway_compat.py`、`tests/test_openai_response_compat.py`、`tests/test_direct_compat.py` 和 `tests/test_compat_transport_faults.py`。
