# Context windows and compaction

Automatic compaction uses Pi’s native policy and the current model’s effective
context window. The Agent settings toggle controls whether it runs. Pi’s
reserve and retention settings apply as configured in Pi.

## Provider-reported limits

For OpenAI-compatible and Anthropic-compatible accounts, save the account, open
its model mappings and select **Refresh model information**. This reads the
provider's `/models` catalog (Anthropic uses `/v1/models` unless the configured
base already ends in `/v1`) and updates metadata for matching model IDs while
keeping your mappings. Anthropic-style `has_more` / `last_id` pagination is
supported. Imported providers supply the same information during their normal
model refresh.

Recognized fields are `max_model_len`, `context_length`, `context_window`,
`max_context_length`, `max_input_tokens`, `contextWindow` and `inputTokenLimit`.
The same fields are recognized inside `top_provider`, `limits`, `capabilities`,
`model_info`, `metadata` and `parameters` (up to three nested containers), for
example `top_provider.context_length` and `model_info.max_input_tokens`. If
several input/context capacities are reported, the smallest one is used;
output-only limits are skipped. Without valid metadata, the model-name
suggestion applies.

An example of a nested catalog field is documented in the
[OpenRouter model-list response](https://openrouter.ai/docs/api/api-reference/models/list-all-models-and-their-properties).

The saved `providerContextWindow` is read-only metadata. In automatic mode it
takes precedence over model-name suggestions and the 128,000-token fallback.
A context window you set yourself takes precedence over both.

## Manual compaction and history

Hover over the context-usage circle below the composer to inspect usage. Click
the circle and choose **Compact context**. The action is available while the
current conversation is idle. It uses Pi’s compaction and keeps the composer
draft. The Agent can also run native commands through `run_pi_command`.

Automatic and manual compaction create a muted, collapsible event at their
chronological position in history. The event updates from progress to success
or failure. Expand it to inspect the summary, errors and before/after token
estimates. These events are shown locally only; the model does not receive them.
They survive reopening and history paging. The temporary composer status
clears when compaction finishes. Post-compaction token counts are Pi estimates.

---

自动压缩沿用 Pi 原生策略，使用当前模型的有效上下文窗口；Pi 的预留和近期保留设置
照常生效。供应商报告的窗口可单独刷新；没有手动设置时优先使用服务端值，没有服务端
值时按模型名匹配或使用 128000 默认值。

悬停输入框底部的上下文圆环可查看用量，点击后选择“压缩上下文”。该操作在当前会话
空闲时可用，输入框草稿保持不变。Agent 也可以通过 run_pi_command 使用原生命令。

自动和手动压缩均在历史中显示可展开事件，从进行中更新为成功或失败；展开可查看
摘要、错误和压缩前后 token 估计值。这些事件只在本地显示，模型收不到；重开会话和
分页后仍保留。
