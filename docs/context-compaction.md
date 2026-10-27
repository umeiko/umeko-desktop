# Context windows and compaction

In **Settings → Accounts & Providers**, edit a model or open its model mappings.
**Compaction threshold** sits beside **Context length** and accepts an integer
token count. Leave it empty to keep Pi's native policy (normally the context
window minus 16,384 tokens, with a recent-token budget of 20,000). The existing Agent
auto-compaction switch still controls whether automatic compaction runs.

For an explicit threshold `T`, Umeko sets a session-only Pi model override:

```text
reserveTokens    = contextWindow - T
keepRecentTokens = min(native keepRecentTokens, floor(T / 2))
```

The native recent-token default is 20,000. The threshold must be at least 1,024
and at most the effective context window; a known provider limit is also an
upper bound. For a 128,000-token window and threshold 20,000, the default mapping
is reserve 108,000 and recent-token budget 10,000. A threshold equal to the window
uses reserve zero, which Pi supports. Settings are saved per model and reapplied
when switching models or resuming a conversation. Native/project settings files
are not rewritten. The output-token setting keeps its existing behavior.

Pi uses estimated context tokens and checks at native turn boundaries, so this
is a trigger target rather than an exact token interrupt. The current request
can take usage past the threshold before compaction starts. The reported
post-compaction count is Pi's estimate, not a new provider usage measurement.
Retention follows native message/turn boundaries and can exceed the configured
recent-token budget.

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
A user-defined context window still wins for the window setting, while an
explicit compaction threshold cannot exceed the provider's reported capacity.
An excessive threshold is rejected with the numeric limit in Chinese and
English. Refreshing to a capacity incompatible with an existing threshold
reports that limit and preserves the previous settings; lower the threshold and
refresh again.

## Manual compaction

Type `/compact` in the composer and press **Enter**. Optional text, such as
`/compact preserve the current task`, goes directly to Pi as custom compaction
instructions. The slash command is handled locally. If a turn is running, the
status line says compaction is waiting and runs it when that turn ends.

On success, the conversation contains a persistent line such as
**Compacted: 22000 → 9000 tokens** (Chinese: **已压缩：22000 → 9000 tokens**).
The summary itself is not displayed. Failures appear as plain text; provider
request diagnostics remain available through the existing error-details view.

---

在 **设置 → 账号与供应商** 中编辑模型，或打开模型映射，在“上下文长度”旁填写
“压缩阈值”。留空沿用 Pi 原生设置；显式值最小为 1024 token，不能超过实际窗口及
已知的供应商上限。“刷新模型信息”会读取服务端模型列表并保存窗口数据，自动模式
优先使用该值。供应商未提供窗口时，继续按模型名匹配或使用 128000 默认值。

在输入框输入 `/compact` 并按 Enter 即可手动压缩，也可输入
`/compact 保留当前任务`。忙碌时会显示等待状态，当前任务结束后执行。完成后显示
压缩前后的 token 数，压缩后数字为 Pi 估计值；摘要不显示在聊天中。
