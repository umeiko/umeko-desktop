# Context windows and compaction

Automatic compaction uses Pi’s native policy and the current model’s effective
context window. The existing Agent settings toggle controls whether it runs.
Umeko does not add a per-model trigger or change Pi’s reserve/retention settings.

## Provider-reported limits

For OpenAI-compatible and Anthropic-compatible accounts, save the account, open
its model mappings and select **Refresh model information**. This reads the
provider's `/models` catalog (Anthropic uses `/v1/models` unless the configured
base already ends in `/v1`) and updates metadata for matching model IDs without
replacing your mappings. Anthropic-style `has_more` / `last_id` pagination is
supported. Imported providers supply the same information during their normal
model refresh.

Recognized fields are `max_model_len`, `context_length`, `context_window`,
`max_context_length`, `max_input_tokens`, `contextWindow` and `inputTokenLimit`.
The same fields are recognized inside `top_provider`, `limits`, `capabilities`,
`model_info`, `metadata` and `parameters` (up to three nested containers). This
covers, for example, `top_provider.context_length` and
`model_info.max_input_tokens`. If multiple valid input/context capacities are
reported, the smaller value wins; output-only limits are ignored. Missing or
invalid metadata adds no provider cap.

An example of a real nested catalog field is documented in the
[OpenRouter model-list response](https://openrouter.ai/docs/api/api-reference/models/list-all-models-and-their-properties).

The saved `providerContextWindow` is read-only metadata. In automatic mode it
takes precedence over model-name suggestions and the 128,000-token fallback.
A user-defined context window still takes precedence when explicitly configured.

## Manual compaction and history

Hover over the context-usage circle below the composer to inspect usage. Click
the circle and choose **Compact context**. The action is disabled while the
current conversation is busy. It uses Pi’s existing compaction path and leaves
the composer draft intact. The Agent can also invoke native commands through
`run_pi_command`; the composer does not interpret slash commands.

Automatic and manual compaction create a muted, collapsible event at their
chronological position in history. The event updates from progress to success
or failure. Expand it to inspect the summary, errors and before/after token
estimates. These are local display metadata, not assistant replies or model
messages. They survive reopening and history paging. Temporary composer status
clears when compaction finishes. Post-compaction token counts are Pi estimates.

---

自动压缩沿用 Pi 原生策略，使用当前模型的有效上下文窗口，不增加每模型压缩阈值，
也不改变 Pi 的预留和近期保留设置。供应商报告的窗口可独立刷新；未手动覆盖时优先
使用服务端值，缺失时继续按模型名匹配或使用 128000 默认值。

悬停输入框底部的上下文圆环可查看用量，点击后选择“压缩上下文”。当前会话忙碌时
该操作不可用，输入框草稿保持不变。Agent 仍可通过 run_pi_command 使用原生命令。

自动和手动压缩均在历史中显示可展开事件，从进行中更新为成功或失败；展开可查看
摘要、错误和压缩前后 token 估计值。事件只属于本地显示元数据，不成为助手回复，
不进入模型消息；重开会话和分页后仍保留。
